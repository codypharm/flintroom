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
pending ──► extracting ──► ready
                     └──► failed
```

`POST /v1/sessions` rejects a material that is not `ready` with a typed 422.

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

**Two controls, doing two different jobs.** A single daily number cannot do
both — rehearsal is bursty by the same logic that put the minutes allowance on a
monthly reset, so a ceiling loose enough for a real preparation evening is
catastrophic if drawn every day for a month.

| Control | Where | Varies by tier | Job |
| --- | --- | --- | --- |
| Monthly page budget | `billing/tiers.py` | **Yes** | Protects margin, which is measured monthly |
| Daily page ceiling | `Settings` | No | Stops a runaway — a loop, a bug, a script |
| Max pages per material | `Settings` | No | A 500-page PDF is a parsing problem at any price |
| Max upload bytes | `Settings` | No | Memory during render, and mobile upload reality |

The budget goes beside `MONTHLY_ALLOWANCE_SECONDS`, whose docstring already
states the terms this inherits: *"policy, not arithmetic — they move when pricing
moves, and pricing cannot move without the §4.3 cost-instrumentation task behind
it."*

**The free tier's budget is lifetime, not monthly.** Its minutes already are —
`FREE_TIER_LIFETIME_SECONDS`, granted once, deliberately absent from the monthly
table. A renewing page budget on a tier with no renewing minutes turns the free
tier into an unlimited extraction faucet: sign up, never start a session, extract
decks forever at our cost with no metered minute ever consumed.

```
free      100 pages  LIFETIME
starter   600 pages/month
pro      1200 pages/month
teams     600 pages/seat/month

MAX_PAGES_PER_MATERIAL = 100
MAX_UPLOAD_BYTES       = 25 MB
DAILY_PAGE_CEILING     = 200
```

**Set as an invisible backstop, not a stated entitlement.** Real use is on the
order of 40–80 pages a month, so no legitimate user meets these. Nothing is shown
in the UI — a visible page budget would contradict §4.4's *"unlimited material
storage"* in spirit, and a counter of any kind runs into the rule against
depleting counters. Exceeding it is an error, never a paywall.

Worst case at Pro is roughly $12 a month against $29.90 of margin, on an
unverified ~$0.01/page. That estimate is the weakest number here and the reason
these are provisional: tighten them against observed `extraction_costs`, not
against this paragraph.

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

- **Every limit above is provisional**, resting on an unverified ~$0.01 per page.
  They are deliberately set as a backstop rather than a budget, so being wrong by
  2× is survivable — but they are the first thing to revisit once
  `extraction_costs` has real data, and they must not be cited as if measured.
- **Two dependencies to justify when they land:** LibreOffice (a large binary, run
  as a subprocess) and `python-pptx`. Both are PPTX-only; nothing else in the
  pipeline needs either.
- **Per-seat accounting for Teams is unspecified.** The budget is written per
  seat, and nothing yet says whether an unused seat's pages pool across the
  organisation. It does not block anything until Teams ships.
