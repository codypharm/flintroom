# Context Ingestion

**Status:** decided 2026-08-15. Builds in Phase 1 (Weeks 1–2) per `Product.md` §7,
outstanding because it was skipped when the voice loop went first.

Resolves how attached material becomes something the Auditor can cross-check
against. `Product.md` §3.2 specifies this in one table row and four bullets;
everything below is what that turned into once the questions were asked.

> **Naming.** *Material* is the ingested artefact. *Claim* is the unit the
> Auditor compares — defined in `docs/auditor-grounding.md`, and this document
> does not redefine it. *Auditor* is the domain agent, never the `audit_log`
> module.

---

## Problem

`Product.md` §3.3 defines the Auditor as mapping *"the live transcript against
ingested material."* Nothing ingests anything. There is no `ingestion` module, no
object storage of any kind, and no table that holds a claim or a figure. Nine ORM
models exist and not one of them is about content.

`POST /v1/sessions` also takes no request body at all — a session is *"open a room
for the caller"* and carries no configuration. So material has nowhere to attach
even if it existed.

The stakes are Open Risk #2: *"Ungrounded generic questions kill retention faster
than any UI flaw."* Half the Auditor's job — cross-checking a spoken figure
against the deck it came from — has nothing to operate on until this exists.

---

## Decisions

### Material is owned by the user, not by a session

A `Material` belongs to an account and sessions reference it through a join. The
product's premise is repeat rehearsal before one high-stakes event, so a deck
uploaded once and used across five sessions is the normal case, not an
optimisation. Re-uploading per session would also pay the extraction bill again
every time, and extraction is the expensive part.

It also puts retention on the material, which is the thing a privacy policy is
actually written about — rather than on a session, whose own retention is a
separate and still-undecided question (task #29).

### Extraction is asynchronous, and a session refuses material that is not ready

```
awaiting_upload ──► pending ──► extracting ──► ready
       │                                 └──► failed
       └──► (reaped — a presign nobody used)
```

`POST /v1/sessions` rejects a material that is not `ready` with a typed 422.

**`awaiting_upload` was added 2026-08-16**, when building the model showed four
states could not carry the upload handshake. A row has to exist before the bytes
do — that is what the presign is signed against and what ownership is checked on
— so `pending` would have meant both *"no bytes yet"* and *"bytes here, waiting
its turn"*, and the extraction sweep claims `pending`. As specified, it would
have claimed materials nobody ever uploaded.

A state rather than a nullable `uploaded_at`, which is the shape
`Session.grace_started_at` uses. That precedent turns on nothing behavioural
changing during grace; here the thing that changes is whether the extractor may
claim the row, which is the distinction the precedent was drawing. It also keeps
two unrelated failures apart: a presign nobody used and an extraction that
stalled want different reap windows, and as separate states that is two obvious
queries rather than one predicate with a null check in it.

The alternative — letting slides land during a live interrogation — was refused
on grounding correctness rather than complexity. The Auditor's reference set would
mutate mid-session, so the same spoken claim could pass at minute two and fail at
minute six. That makes *"why did the panel miss that"* unanswerable, and grounding
quality is the correctness bar for this whole area, not a nice-to-have.

Synchronous extraction was refused on the input: a forty-slide deck is minutes of
wall clock, which exceeds mobile HTTP timeouts and dies to any network blip with
the entire extraction cost already spent and nothing stored.

**The wait is honest.** Material is attached during setup, and the deckless path
is first-class (`docs/auditor-grounding.md`) — a user who does not want to wait
starts without a deck rather than being blocked.

### Extraction runs in the sweep loop, on claimed rows

A third sweep beside the meter and the reaper, claiming work with
`FOR UPDATE SKIP LOCKED`.

The existing sweeps justify running in every API process on the grounds that they
are idempotent, so *"two processes running them at the same moment reach the same
answer and the second one's writes are refused as duplicates"*
(`sessions/runner.py`). **Extraction does not have that property.** A duplicate
run is not a refused write, it is a second invoice. So the database becomes the
lock and overlap becomes impossible rather than harmless.

Two things this must carry, both of which fail quietly if forgotten:

- **`claimed_at`, with stale claims requeued.** A process that dies mid-extraction
  leaves a row in `extracting` forever. This is the same crash-safety problem the
  `finalizing` session state already solves for settlement — *"nothing separates
  'finished settling' from 'died halfway'"* — and it has the same answer.
- **Rasterization in `asyncio.to_thread`.** Parsing and rendering are CPU-bound
  and will block the event loop, which degrades API latency for every concurrent
  request in that process. The dominant cost is model calls, which are IO, so this
  is cheap to get right and invisible when got wrong.

Both a broker and a separate worker entrypoint were considered. Neither buys
throughput at any volume this product will reach — `FOR UPDATE SKIP LOCKED`
sustains thousands of claims per second, and extraction arrives at roughly one per
user per prep session. What they buy is process isolation and retry machinery.

> **Trigger to revisit:** extraction wait-to-claim p95 exceeds one sweep interval,
> or a material upload measurably degrades API p99 on the same process. Because
> the extractor never learns how it got its job, moving it to a worker or a broker
> is a deployment change rather than a rewrite — the same property
> `docs/deferred-scale-work.md` protects everywhere else.

### Object storage sits behind an interface, and dev runs the real thing

One `ObjectStorage` protocol — `presign_put`, `presign_get`, `delete` — with an
S3-compatible implementation. MinIO joins Postgres in `backend/docker-compose.yml`
so development and CI exercise real presigned PUT and GET rather than a stub.

CLAUDE.md already requires presigned delivery (*"never proxied"*) and an interface
whose *"contract is the presigned URL, not the vendor SDK."* What is decided here
is that the local implementation is not a filesystem shim. A filesystem cannot do
direct-to-storage PUT without proxying — the thing forbidden in production — so a
shim would mean the presigned path is never exercised until deploy. That is
precisely the failure `DATABASE_URL` produced: the configuration looked correct
and the process disagreed. One container is cheaper than that class of bug.

Supabase Storage was refused. The locked architecture decision scopes Supabase to
*"managed Postgres + RLS only"* so that leaving is a `pg_dump`; storage would
re-open it for no capability we cannot get elsewhere.

### The extraction model is chosen independently of the panel LLM

`ExtractionModel` is a Protocol with one module per vendor and a
`build_extraction_model(settings)` that branches on `EXTRACTION_PROVIDER` —
structurally identical to `build_voice_provider`, which exists to make swapping a
vendor *"a sibling module rather than an edit to the relay."*

No model was named anywhere in this project before now. The stack table says
*"vision model"* and `Product.md` §3.2 says *"vision model extraction"*; neither
names a vendor. Task #13 parks the same question for the panel LLM behind #15.

**Extraction is not parked behind #13, because the two jobs have opposite
requirements.** Extraction is batch, latency-insensitive, structured-output, run
once per deck; the panel is conversational and dies above ~1.5s. Coupling them
would make ingestion inherit Phase 3's blockage and buy nothing.

**Claude is the first adapter.** It accepts a PDF directly and processes each page
as text and image together, which matters more than it first appears: **chart data
is not in the text layer.** §3.2 asks for *"claims, figures, and chart data"* per
slide, and `pypdf` returns a chart's axis labels and none of its values. Batch
pricing roughly halves cost and extraction is latency-insensitive, so that
discount is free here.

The interface takes rendered pages plus text, not a PDF. A model without native
document input must still be usable, and an interface that promises what only some
vendors can honour turns a configuration error into a runtime failure.

### The PDF engine is pypdfium2, and the reason is a licence

**Decided 2026-08-16.** Verified from installed package metadata rather than
recalled:

| Library | Licence | Size |
| --- | --- | --- |
| `pypdfium2` 5.13 | BSD-3-Clause, Apache-2.0 | 7.3 MB |
| `PyMuPDF` 1.28 | **AGPL-3.0 or Artifex commercial** | 54 MB |
| `pypdf` + poppler | MIT + GPL-2.0 binary | small + a system package |

PyMuPDF is the better extractor and was refused on its licence. AGPL §13 obliges
software that users *interact with over a network* to offer them its source, and
a hosted backend is that case exactly — so it is a licence purchase and a vendor
relationship rather than a dependency. Not a decision to take by accident, which
is what taking it on extraction quality alone would have been.

pypdfium2 does rendering and text in one library, ships wheels, and needs no
system binary. PDFium is the engine in Chrome, so a page renders the way the
author's browser would show it. Its layout reconstruction is weaker than
PyMuPDF's, which matters less here than it looks: the model sees the image of
every page as well as the text, and exact chart values come from PPTX XML where
they exist at all.

`pypdf` plus a poppler subprocess was the third option — two dependencies for one
job, one of them a second external binary to install, version and debug beside
LibreOffice.

### A page is rendered at 1568px, and stripped of everything the camera attached

`RENDER_LONG_EDGE = 1568` is where vision models stop gaining detail. Larger and
the model downscales it anyway, so the extra pixels are paid for in memory and
upload and then discarded; smaller and small figures on a dense slide stop being
legible — the failure that matters, since a misread number in a panelist's mouth
is what `docs/auditor-grounding.md` says the grounding story cannot survive.

Rendered pages are PNG and photographs are JPEG. Not an inconsistency: a rendered
slide is flat colour and sharp type, where PNG compresses well and JPEG puts
ringing artefacts around exactly the small digits being read; a photograph is
sensor noise, where PNG is enormous and losslessness buys nothing.

**EXIF orientation is applied and the rest is dropped.** Phones record which way
is up rather than rotating the pixels, so a portrait whiteboard arrives as a
landscape image with a note attached — ignore the note and the model gets a
sideways slide, which reads as a bad model rather than as a bug. Everything else
in that block is metadata nobody uploaded, and a photograph of a whiteboard
records where it was taken. The page image outlives the source document, so this
is not a detail that can be added later.

### The model extracts, code computes — inherited, not restated

`docs/auditor-grounding.md` fixes this and ingestion does not get to differ: the
extraction model's only job is pulling figures into a typed claim. Every derived
figure is ordinary arithmetic, so *"arithmetic hallucination becomes impossible
rather than discouraged."*

### A claim is one shape, stored in two tables

`Claim` — value, unit, metric, period — is shared, because the Auditor's entire
function is comparing a slide claim against a spoken one and they must be
comparable. Unit and period are load-bearing, not decoration: *"most false
positives come from comparing figures that were never comparable."*

The locators differ and so do the lifecycles, so the storage is separate:

| Table | Locator | Retention |
| --- | --- | --- |
| `material_claims` | `material_id`, `slide_no` | Until the user deletes the Material |
| `session_claims` | `session_id`, `offset_ms` | Undecided — task #29 |

One table with a source discriminator would be a simpler query and was refused for
that retention split: deleting a session would mean surgically removing some rows
from a store governed by another policy, which is where retention bugs live.

### The source document is deleted once extraction succeeds

What survives is the extracted claims and a downscaled first-page thumbnail
(~20KB). The uploaded PDF or PPTX is deleted from object storage.

A deck is the most confidential thing this product will ever hold, and the source
document's only remaining jobs are reprocessing and support debugging — neither of
which justifies an indefinite pile of other people's unannounced financials. It
also makes a checkable promise for the App Store questionnaire that Open Risk #5
says must be ready in advance rather than written the week of submission.

**The thumbnail is not automatically the low-sensitivity artefact it sounds
like** — a title slide routinely carries the company name, the round size and the
word "Confidential." It therefore inherits the claims' retention and deletion
rules exactly, and is never weaker.

Cost: improving the extraction pipeline cannot reprocess existing material, and
support cannot see a source document when asked why the Auditor missed something.
Both were accepted knowingly.

### Extraction cost is recorded, and page throughput is capped

An `extraction_costs` table keyed by `material_id` and `user_id`, recording
provider, model, pages and token counts.

Session-scoped `session_costs` cannot hold this. The metering boundary is locked —
only live interrogation is metered — so **extraction is a real per-user cost with
no revenue attached**, and the abuse case is precisely a deck that is extracted and
never becomes a session. Attributing cost to the session that used the material
would leave exactly that case invisible.

It caps pages, not stored materials, and the distinction is deliberate: §4.4
sells *"unlimited material storage"* as a Pro capability, and storage is nearly
free here by construction since originals are deleted and thumbnails are tiny.
Pages extracted and materials stored are different nouns, and only one of them
costs money.

**Four controls, doing three different jobs.** A single number cannot do them
all — rehearsal is bursty by the same logic that put the minutes allowance on a
monthly reset, so a ceiling loose enough for a real preparation evening is
catastrophic if drawn every day for a month.

| Control | Where | Per tier | Published | Job |
| --- | --- | --- | --- | --- |
| Max pages per material | `billing/tiers.py` | **Yes** | **Yes — tier cards** | Sells the upgrade, at the one moment a buyer can answer it |
| Max upload bytes | `billing/tiers.py` | **Yes** | **Yes — tier cards** | Same, plus memory and mobile-upload reality |
| Monthly page budget | `billing/tiers.py` | **Yes** | No | Protects margin, which is measured monthly |
| Daily page ceiling | `Settings` | No | No | Stops a runaway — a loop, a bug, a script |

All three per-tier figures go beside `MONTHLY_ALLOWANCE_SECONDS`, whose docstring
already states the terms they inherit: *"policy, not arithmetic — they move when
pricing moves, and pricing cannot move without the §4.3 cost-instrumentation task
behind it."*

```
                 per file        upload      extraction budget
free             20 pages         10 MB      100 pages LIFETIME
starter         100 pages         25 MB      600 pages/month
pro             300 pages        100 MB     1200 pages/month
teams           100 pages         25 MB      600 pages/seat/month

DAILY_PAGE_CEILING = 200          (Settings, uniform)
```

### Why the per-file cap is the published one

The monthly budget is the number that protects margin, and it is exactly the
wrong number to advertise: **nobody can estimate their own monthly page volume at
signup.** A buyer can answer "how big is my deck" instantly, so the per-file cap
is legible at the moment the upsell has to land, and the monthly budget is not.

§4.6 endorses this shape — *"lead with the largest honest unit"* — and its warning
against rationing is about a **depleting counter in the app**, not a quantity on a
tier card. "3 hours of interrogation" is already such a quantity.

Publishing the per-file cap also leaves §4.4 intact. *"Unlimited material
storage"* is about how **many** materials you may keep, not how large each one is,
and the count stays genuinely unlimited. Publishing the monthly budget is what
would have contradicted it.

**The monthly budget and daily ceiling stay unpublished**, in the same category as
§4.7's existing *"per-account daily spend ceiling as a runaway-cost circuit
breaker"* — a safeguard, not an entitlement. Real use is 40–80 pages a month
against 600 allowed, so no legitimate user meets them, and leaving them
unpublished keeps them a dial rather than a promise. That matters because they
rest on an unverified ~$0.01/page: publishing a number derived from an estimate
converts it into something that cannot be tightened without notifying customers.

Worst case at Pro is roughly $12 a month against $29.90 of margin, on that same
unverified figure. It is the weakest number in this document, and the reason every
limit here is provisional: tighten them against observed `extraction_costs`, not
against this paragraph.

### Two consequences of publishing per-tier caps

**The presign needs the caller's tier.** Validation happens before the presigned
URL is issued, so the upload path now reads `Account.entitlement_tier` — it is no
longer a pure function of the file. Cheap, since it is a column on a row the
request already touches.

**Refusing an oversized upload is a legitimate paywall, and the only one here.**
CLAUDE.md forbids interrupting a *live session* to show a paywall; this is a
pre-session refusal on a published limit the user chose their plan against, which
is a different thing entirely. It should name the tier that would accept the file
and offer the upgrade. Do not let this precedent drift toward the forbidden case.

### The byte cap is enforced by the signature, not by our arithmetic

**Decided 2026-08-16, after probing a real S3 server.** SigV4 covers every header
it lists in `SignedHeaders`, and `Content-Length` and `Content-Type` can both be
put there. Verified against MinIO rather than assumed:

```
X-Amz-SignedHeaders=content-length;host
  a body of the declared length      200
  a larger body                      403 SignatureDoesNotMatch
  no Content-Length at all           411 MissingContentLength
  a different Content-Type           403
```

So `presign_put(key, content_length=, content_type=)` takes both, and the tier
cap becomes a property of the upload rather than a number checked once at
registration. Without this, the declared size is a courtesy: a client asks for a
URL saying 8MB and then sends four hundred, and the only limit is whatever the
bucket happens to allow.

Two consequences to know before they bite:

- **It signs one exact length, not a range.** A client that does not know its own
  file size cannot upload. Every source we accept comes from a file handle that
  does, so this costs nothing today — but it rules out a streaming producer.
- **It is a single PUT, so there is no resume.** A dropped mobile connection
  restarts the whole upload, which is tolerable at 10MB and unpleasant at 100.
  The fix when it bites is a multipart presign, which boto3 already implements —
  one of the reasons it is the SDK in `storage_s3.py`.

`byte_size` is therefore safe to store and compare against without re-reading the
object: the row's number and the object's number cannot disagree.

### The refusal states the fact and then the fix

**Decided 2026-08-16.** The tone is fixed, and it is the tone of a limit rather
than of a pitch:

> That file is 12 MB. Your plan accepts up to 10 MB. Starter accepts up to 25 MB.

No apology, no verb of persuasion. The upgrade is stated as an available fact and
the client draws the button beside it. Three rules follow, each of which is a way
the message could quietly stop being true:

- **It names the cheapest tier that would take the file, not the largest.** The
  message's entire credibility comes from reading as a fact, and a fact that
  happens to sell the most expensive plan is not one.
- **When no tier accepts the file, it offers nothing** and states the ceiling
  instead. Selling a plan that still refuses the upload is the one outcome this
  paywall may not produce.
- **A wrong file type is a separate error and never carries an upgrade**, because
  no tier accepts an executable. Merging the two is how a type refusal grows an
  upsell it has no right to make.

The file's size rounds **up** to one decimal and the cap does not, so the two
numbers in the message can never collide. A file one byte over the cap would
otherwise read *"That file is 10 MB. Your plan accepts up to 10 MB"* — a message
that earns a support ticket where it should have earned an upgrade.

### The caps are published, and the client refuses locally

`GET /v1/materials/limits` returns the caller's caps, the accepted content types,
and the rung above if there is one. The app refuses an oversized file against
that — instantly, offline, before it reads a byte — and the server refusal stays
the real wall.

The alternative was the app holding its own copy of the tier table, where a
pricing change ships as an app release and the two disagree without anyone
noticing. Since `Product.md` §4.4 already publishes these numbers on tier cards,
serving them is not a disclosure; holding them in two places is just a way for
one of them to go stale.

### `complete` checks the store before believing the client

The client saying the bytes landed is a claim, and it is verified with one HEAD
before the material moves to `pending`.

`pending` is the state the extraction sweep claims, so it is the moment a
material starts costing money. Without the check, a client that never uploaded —
or whose PUT failed while its retry logic reported success — puts a row into the
queue pointing at nothing: the sweep claims it, pays to open an object that is
not there, fails, and requeues. One round trip turns that into a refusal at the
handshake, while the user is still on the screen that can do something about it.

**The free tier's budget is lifetime, not monthly.** Its minutes already are —
`FREE_TIER_LIFETIME_SECONDS`, granted once, deliberately absent from the monthly
table. A renewing page budget on a tier with no renewing minutes turns the free
tier into an unlimited extraction faucet: sign up, never start a session, extract
decks forever at our cost with no metered minute ever consumed.

Exceeding a limit is a typed 422 with an `audit_events` row; the material stays
`pending` rather than failing, so it extracts when the window rolls over.

---

## Modules

```
backend/app/core/
  storage.py            ObjectStorage protocol
  storage_s3.py         S3-compatible implementation (MinIO in dev)

backend/app/modules/ingestion/
  router.py             thin: presign, complete, read, delete
  service.py            material lifecycle, claim persistence, page ceiling
  extractor.py          the sweep pass — claim, extract, settle, requeue stale
  parsing.py            PDF/PPTX/image → rendered pages + text + exact
                        chart values where the format carries them (no model)
  model.py              ExtractionModel protocol
  models/
    __init__.py         build_extraction_model(settings)
    claude.py           first adapter
  models.py             Material, MaterialClaim, ExtractionCost ORM
  schemas.py            Claim, MaterialRead, MaterialState
```

`parsing.py` and the derived-figure arithmetic are the deep modules here — both
are pure functions over bytes and typed claims, testable with no model, no
network and no database.

---

## Input types

Four inputs, one pipeline. Everything below `parsing.py` is identical.

| Input | Pages | Vision needed | Notes |
| --- | --- | --- | --- |
| PDF | many | Yes — chart values | Native document input on the first adapter |
| PPTX | many | Partly — see below | Rendered *and* read structurally |
| Slide/whiteboard photo | one | Yes | The mobile-native case, §3.2 |
| Pasted text | one | No | Skips rasterization entirely |

Pasted text still needs the model, because identifying a *claim* in text is a
semantic job even when no image is involved. Only rasterization is skipped.

### PPTX is read twice, and the exact numbers win

Headless LibreOffice converts to PDF so PPTX rejoins the PDF path for thumbnails
and vision. Separately, `python-pptx` reads the file structurally — and for a
chart authored in PowerPoint, `Series.values` is documented as *"a sequence
containing the float values for this series, in the order they appear on the
chart."*

**Those exact values beat anything vision infers from pixels, and win on
conflict.** A misread figure put confidently into a panelist's mouth is the one
failure `docs/auditor-grounding.md` says the grounding story cannot survive, so
where PowerPoint stored the number, we read the number.

Rendering is still required rather than optional, for two reasons that are easy
to miss:

- **A pasted chart image has no XML data.** Screenshotting from Excel or Tableau
  into a slide is common, and only vision reads that.
- **The thumbnail.** PDFs render easily; PPTX cannot be rendered without
  LibreOffice, so dropping it would mean a placeholder for exactly the file type
  business users bring most.

A hosted conversion API was refused outright: it would ship confidential decks to
a third party, which contradicts the retention decision above.

LibreOffice is a large binary in the image and a subprocess with its own failure
modes. Both were accepted; the alternative was losing pasted charts and PPTX
thumbnails together.

---

## Security

Follows the mandatory rules rather than restating them; the ones with teeth here:

- Uploaded material is delivered by presigned URL only and never proxied.
- Validation happens before the presign is issued, not after the bytes land —
  wrong type is 415 and oversized is 413, and neither should cost an upload.
- `material_claims` and `extraction_costs` carry deny-all RLS without
  `auth.uid()`, like every other table (migration `1f359ab487a7`).
- Extracted claim text is never logged. CLAUDE.md forbids ingested material
  contents in logs, and unlike a secret it is not detectable by key name, so it
  must not be passed at all.
- A presigned GET is scoped to one object and short-lived. A material belongs to
  one account, and the read path checks ownership before signing anything.

---

## Out of scope

- **Session retention.** What a saved session keeps — transcript, audio, or
  neither — is task #29 and `Product.md` §9 lists it as *"undecided, do not
  invent."* Material retention is settled here and does not settle that.
- **Derivation packs.** `docs/auditor-grounding.md` specifies per-segment derived
  figures and plausibility bands. Those consume claims; they are Phase 3.
- **Panel setup.** Sessions still take no configuration beyond material ids.
  Archetype selection and audience context belong with the panel work.
- **Reprocessing.** Deleting the source makes it impossible by design. If pipeline
  improvements later justify it, that is a retention change first and a feature
  second.

---

## Open

- **Every limit above is provisional**, resting on an unverified ~$0.01 per page,
  and two of them are now *published*. That asymmetry is the risk to watch: an
  unpublished backstop can be tightened silently, a tier card cannot. **The
  per-file caps should not appear on a real pricing page until §4.3 has measured
  a page** — publishing them is a pricing action, and CLAUDE.md bars shipping
  pricing that cost instrumentation does not back. Building the per-tier
  mechanism now is not the same act and is not blocked.
- **Two dependencies to justify when they land:** LibreOffice (a large binary, run
  as a subprocess) and `python-pptx`. Both are PPTX-only; nothing else in the
  pipeline needs either. `parsing.py` shipped without them — PDF and photographs
  are pure Python and needed no system package, so PPTX is the only input still
  waiting on a 400 MB binary decision, and it waits alone rather than holding the
  module back.
- **The per-file page cap fails a material terminally; the monthly budget does
  not.** This document says *"the material stays `pending` rather than failing, so
  it extracts when the window rolls over"* — true of the budget and the daily
  ceiling, which are windows, and wrong for the per-file page cap, where no window
  rolls over into a file being shorter. `MaterialTooManyPages` and the budget
  refusal are therefore separate errors. The sweep that acts on them is slice 6
  and this is the reading it should implement.
- **Per-seat accounting for Teams is unspecified.** The budget is written per
  seat, and nothing yet says whether an unused seat's pages pool across the
  organisation. It does not block anything until Teams ships.
