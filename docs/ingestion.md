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

**Built 2026-08-16**, and it is what made every earlier slice reachable: until
then `POST /v1/sessions` took no request body at all, so material had nowhere to
attach even once it existed.

`session_materials` is a many-to-many join with a composite primary key, so
attaching the same deck to one room twice is impossible rather than merely
unlikely. Both sides cascade — deleting a material erases the record that a past
session used it, which is deliberate: `material_claims` cascades too, so the
grounding is gone either way and a link pointing at contents that no longer
exist is a citation nobody can follow.

Three details that are not obvious from the endpoint:

- **The set is fixed at start and there is no attach endpoint.** That is the
  same refusal as above, one layer up: a room that could gain a deck at minute
  four has a reference set that moves mid-session.
- **The readiness check runs before the session row is inserted.** A session
  created and *then* refused would hold the user's one-live-session lock until
  the reaper cleared it, so a mistyped material id would lock somebody out of
  rehearsing for a minute over an attempt that never opened a room.
- **`failed` and `extracting` are one refusal with two messages.** Same answer
  to the room, opposite advice to the person: wait, or upload it again. Telling
  somebody to wait for a deck that will never finish is how a user sits watching
  a spinner that is not spinning.

`MAX_SESSION_MATERIALS = 10` is a guard, not a considered limit. The real bound
is claims rather than files — a single pro-tier deck already carries more than a
context window wants — and whatever replaces it belongs with the panel work.

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

**Built 2026-08-16, and it is a second loop rather than a third sweep.**
`SweepRunner` awaits its sweeps in sequence on a fifteen-second pass. Reading a
pro-tier deck is fifteen model calls behind a CPU-bound render of three hundred
pages — minutes, not seconds — so hanging extraction off that pass would stop
the meter for the duration, and a stopped meter is money never charged for rooms
the provider is still billing us for. That is not a scale concern; it would have
been a billing outage on the first large deck.

The loop paces itself only when idle: it comes straight back while there is a
queue, so a backlog does not cost a user one interval per deck ahead of them.

**Shutdown may cancel it, and that is the second real difference.**
`SweepRunner.stop()` is deliberately not a cancellation because it writes money.
Nothing in extraction is half-writable — the claim, the three endings and the
release are each one transaction — so an abandoned deck is a stale `claimed_at`
that the next process gives back. A deploy takes the deck back rather than
waiting minutes for it, and both alerts are in `docs/deployment.md`.

**One deck per process at a time, which is the deliberate concurrency ceiling.**
The trap named below is that the adapter's four-at-once bounds one *material*
while the rate limit is per organisation. Holding one material per process makes
the fleet's ceiling `processes × EXTRACTION_CONCURRENT_CALLS` — a number that
can be reasoned about before it is met, rather than discovered as a wall of
429s. It is also the first knob to turn if extraction is too slow, and the
trigger to revisit is unchanged: wait-to-claim p95 above one interval.

**The extractor reads the object's bytes directly** (`ObjectStorage.get`), which
is the one method on that interface that returns content. It is not the
delivery path the *"never proxied"* rule governs: that rule is about a deck
travelling through a request handler to a client. Something has to open the file
in order to render it, and the alternative was fetching it from ourselves over
HTTP with a bearer URL minted for the purpose — slower, more code, and one
stray log line away from leaking a credential to a confidential deck.

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
so development and CI exercise real presigned PUT and GET rather than a stub. (RustFS
since 2026-09-28, when MinIO stopped publishing images; the reasons are in
`backend/docker-compose.yml`.)

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

> **Superseded 2026-08-17 (#61). Gemini is the default; both adapters exist.**
> Extraction shipped against Claude alone, with `extraction_provider` a
> single-valued `Literal` — so when the Anthropic account could not be funded,
> switching vendors was not a setting but a missing adapter, and a built feature
> could not run. The failure was the polite kind: `build_extraction_model`
> returns `None` without a key by design, so the process booted, signed people
> in, accepted uploads, and grounded nothing.
>
> `GeminiExtractionModel` is now the sibling module this document always said a
> second vendor would be, and the vendor-neutral half — `to_claims`, the
> locator, the merge — moved to `extraction_models/reading.py` and is shared
> unchanged. **The image-and-text-together property below is preserved and
> asserted on the bytes on the wire**, because an adapter that lost it would
> authenticate, return claims, pass almost every test, and silently drop every
> figure a deck draws rather than writes.
>
> **Every per-page cost figure in this document was estimated against Claude and
> now needs re-measuring.** The reasoning stands; the number moves with the
> vendor.

**Claude was the first adapter, and the reasoning is why both take pages this way.** It accepts a PDF directly and processes each page
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

### Which model is a setting, because it is the cost lever

**Decided 2026-08-16.** `EXTRACTION_PROVIDER` is a `Literal` — a typo refuses to
boot rather than silently meaning "none", which would be a deployment that
starts, signs people in, accepts uploads and grounds nothing. `EXTRACTION_MODEL`
is a plain string defaulting to `claude-sonnet-5`.

The default is a starting point, **not a decision**. Model choice is the largest
single lever on extraction cost, every figure in this document rests on an
unverified ~$0.01 per page, and the honest way to pick is against measured
`extraction_costs` rows rather than against a guess. Keeping it in configuration
is what stops that choice being made by whoever is editing the adapter.

The unit normaliser is the same principle one level down. A model writes `%`,
`percent` and `pct` for the same thing, and left as written those are three
incomparable figures — so a margin restated in different words reads as a
contradiction that is not there. `Unit` is a closed set and `normalize_unit` maps
onto it; anything unrecognised becomes `UNKNOWN`, which nothing compares to.
That costs a missed catch rather than a false accusation, which is the direction
`docs/auditor-grounding.md` says to err in.

### The model extracts, code computes — inherited, not restated

`docs/auditor-grounding.md` fixes this and ingestion does not get to differ: the
extraction model's only job is pulling figures into a typed claim. Every derived
figure is ordinary arithmetic, so *"arithmetic hallucination becomes impossible
rather than discouraged."*

### A claim has two kinds, and only one of them is a number

**Corrected 2026-08-16**, after the first adapter was built extracting figures
only. `Product.md` asks extraction for *"claims, figures, and chart data"* (§3.2),
asks the Auditor for *"contradictions, **unsupported claims**, and figures that
moved"* (§3.3), and defines the wedge as *"a challenge that traces to a specific
**claim, figure**, or slide"* (§9). Claims and figures are distinguished
throughout. This document had collapsed them into one numeric shape.

| Kind | Carries | Compares |
| --- | --- | --- |
| `QUANTITATIVE` | metric, value, unit, period | Exactly. Clears the live-interrupt bar |
| `ASSERTION` | subject, statement | Fuzzily. Debrief only |

**Most of what is attackable in a deck is not a number.** Exclusivity, a granted
patent, a competitive absolute, a commitment about next quarter. Extracting only
figures leaves the Technical Skeptic with no ammunition and makes the panel one
archetype wearing four hats — and `docs/auditor-grounding.md` says qualitative
findings are *"collected and surfaced in the debrief"*, which is impossible if
extraction never captured them.

`AssertionClaim` deliberately has **no** `comparable_to`. The bar for
interrupting a live room is a contradiction stateable precisely — both figures,
both moments — and an assertion cannot meet it. A method that accepted one would
be the route by which fuzzy disagreement reaches the live panel, which is exactly
the false-positive failure the grounding doc refuses.

`subject` on an assertion is load-bearing rather than descriptive: §3.3 assigns
the interrupter by domain, and without it every assertion is unroutable and
targeted interruption quietly covers only numbers.

### The page is looked up where it can be, and admitted to be soft where it cannot

The page is *reported by the model* — it reads `Page 2 text layer:` and writes
back where it found something. That number is not bookkeeping: it is what a
panelist says out loud and what the debrief asks the user to defend. Two
different checks, and they catch different things:

| Check | Catches | Does not catch |
| --- | --- | --- |
| Page exists | Page 99 of a four-page deck | Page 4 labelled page 3 |
| Quote found in a page's text layer | Page 4 labelled page 3 | A figure read off a chart |

The second is the real one. **Which page a piece of text is on is a fact about
the deck, not an opinion of the model's**, so where the text layer settles it,
the claim is moved to the page its quote is actually on. Same *"model extracts,
code computes"* split as the arithmetic, applied to the locator.

Two cases deliberately keep the model's answer. A quote on **no** page is a
figure read off a chart — it lives in the pixels and appears in no text layer,
which is the whole reason a vision model is here. A quote on **several** pages is
a running header, and ambiguous evidence must not override the model, which at
least looked at the images; picking the first match would be inventing a citation
with the confidence of a lookup.

Attribution runs *before* the existence check, so a claim the quote places on a
real page survives however it was originally labelled. Out of range after that is
dropped rather than clamped, because a guessed citation is worse than a missing
claim.

The existence check uses the page *numbers* sent rather than a count, so it
survives being handed a slice of a deck — pages are chunked across calls, and a
chunk holding pages 51–100 has a length of fifty and numbers starting at
fifty-one, so a length check would drop every claim in it.

### A deck is read twenty pages at a time

A full deck does not fit in one call, and the fix lives inside the adapter — a
context window is a vendor constraint, so nothing above `ExtractionModel` learns
that a deck became several requests.

**The chunk size is set by the output limit, not the context window**, which is
the part that surprises. A rendered page costs roughly `width × height / 750`
input tokens — measured at 2,534 for a letter page through this pipeline, about
1,850 for a 16:9 slide — so a pro-tier 300-page deck is ~600k input against a
200k context. But output binds first: at ~6 claims a page and ~60 tokens a
claim, forty pages already brushes `MAX_OUTPUT_TOKENS` and fifty exceeds it.

| Pages per call | Input | Output | |
| --- | --- | --- | --- |
| 20 | ~55k | ~7k | **Chosen** — roughly 2× headroom on the binding constraint |
| 40 | ~110k | ~14k | Output nearly capped |
| 50 | ~137k | ~18k | Truncates |
| 70 | ~190k | — | Context error before it gets there |

The headroom matters more than it sounds. A truncated claim list looks exactly
like a deck with fewer figures on it, nothing downstream can tell, and the
source is deleted afterwards. These numbers are **estimated, not observed** —
`extraction_completed` logs claims per call, so after real decks have run the
size can be set from a measured claims-per-page figure rather than arithmetic.
That is the §4.3 argument applied to context instead of cost.

Calls run four at a time, **per deck**. Sequentially a fifteen-call deck is
minutes of wall clock for somebody who uploaded it in order to rehearse against
it now.

**Four is not the fleet's ceiling, and the difference is a trap.** The semaphore
is created inside `extract`, so it bounds one material; the API key is one
credential for the whole deployment, so the rate limit is spent by every user at
once. A user works one deck at a time — fifty users on a busy evening do not,
and fifty decks at four calls each is two hundred concurrent requests against a
limit that has no idea whose deck is whose.

Nothing hits that today because nothing extracts two materials at once. It
becomes real the moment the sweep exists: **whatever decides how many materials
a sweep pass claims is choosing the actual concurrency ceiling**, and it should
own that number deliberately rather than discover it as a wall of 429s.

**Retries are configured, not inherited.** The SDK retries twice by default;
the adapter asks for four, because one chunk that gives up discards every other
chunk's claims. A second retry layer on top was refused — it would multiply into
nine attempts for one page range, none of them aware of the others.

### One failed call fails the whole deck

Partial storage was considered and rejected. A partially-read deck grounds less
than the user believes, nothing downstream can tell the difference, and the
source is deleted on success — the gap would be permanent and invisible, against
*"extraction completeness is a one-way door, not a backlog item."*

What varies is whether it is worth trying again, and that is decided by **why**
calls failed rather than by how many:

| The failure | `retryable` | Ending |
| --- | --- | --- |
| Every call answered | — | `settle_extraction` → `ready` |
| 400, 413, 422 **and a sibling chunk succeeded** | false | `fail_extraction` → `failed` |
| Rate limit, timeout, 5xx, bad credential | true | `requeue_extraction` → `pending`, later |
| Nothing answered at all | true | `requeue_extraction` → `pending`, later |

Three details are load-bearing, and each closes a way of destroying a deck that
was never the problem:

- **Under load, retries exhaust unevenly.** Some chunks land and some do not, so
  a *partial* failure is the likely shape of a rate-limit event rather than a
  rare one. Reading that as "this deck is unreadable" turns a capacity problem
  into data loss, because `failed` is terminal and tells the user to re-upload.
- **A permanent refusal needs a sibling that worked.** A malformed tool schema
  is a 400 on every call, and without that evidence we would permanently fail
  every deck uploaded while the bug was live. Deny by default, applied to
  destroying somebody's document.
- **One permanent refusal outranks any number of transient ones.** Retrying
  cannot fix it, and a deck left retryable would spin through the sweep failing
  identically every pass.

`extract` never raises. A caller that has to handle both a return value and an
exception for the same question is one that will handle a case wrong, and this
is the seam a second vendor implements. It also makes the cost recordable:
calls are on the invoice whether or not their answers were usable, and cost that
cannot be reconciled is worse than cost that was wasted.

`settle_extraction` refuses an incomplete result outright — `ready` is the
promise the panel grounds itself on.

### A requeued deck waits, and eventually gives up

`pending` **is** the queue, so requeueing is one `UPDATE` — no broker, no second
source of truth about what work exists.

`retry_at` puts the backoff on the row rather than in a sleeping worker, because
the worker that would sleep is the one every other deck is waiting on. It doubles
per attempt from one minute, capped at thirty: linear backoff against a rate
limit is a slower stampede rather than a smaller one, since every requeued deck
returns together and spends the allowance in the instant it recovered.

`attempts` counts **only retryable endings** — ten of them, spanning a few hours.
A deck the API refuses outright fails on the first attempt and needs no budget.
The generosity is the point: a small budget would deliver exactly the data loss
the classifier prevents, just an hour later. The floor exists only so a
pathological deck cannot be claimed forever.

`extraction_costs` gets no row when nothing was billed. An attempt where every
call was rate-limited describes no work, and a row per failed sweep pass would
bury the rows that do.

### A claim records whether its citation was checked

The same search answers two questions, and they are not the same question:

- **Is this really the deck's words?** → `ExtractedClaim.quote_verified`
- **Which page did they come from?** → `ExtractedClaim.page`

A running header appears on every slide: that the deck says it is not in doubt,
while *which* page it came from genuinely is. So a quote found on several pages
is verified but not moved — marking it unverified would throw away a fact we have
over one we do not.

`quote_verified` is False for a figure read off a chart, which appears in no text
layer. **Those claims are not worse, they are unconfirmable** — and being
unconfirmable is worth recording rather than silently mixing in, because they are
also exactly the figures a CFO archetype would press hardest on. Open Risk #2 is
that ungrounded questions kill retention; this makes the ungrounded share
countable instead of argued about.

Defaults to False. A flag defaulting to True is a future adapter silently
asserting a check that nothing performed.

**`ExtractionResult.corrected` counts the moves, and it is not an error count.**
It is the only measure of how far the model's own attribution can be trusted, and
that rate is what should decide whether a page stays the locator at all. If it
turns out to be high on real decks, the honest response is a coarser locator — a
section rather than a page — rather than a precise number that is quietly wrong.
Nothing in the product needs to *display* a page, so the locator's job is
citation, and `quote` already carries the exact words.

**Why this could not wait.** The source document is deleted once extraction
succeeds, and this document already accepts that *"improving the extraction
pipeline cannot reprocess existing material."* Anything not extracted is gone
permanently — so extraction completeness is a one-way door, not a backlog item.

**What it costs.** Assertions are the more numerous kind on most slides, so
output tokens roughly treble while input does not move. Output is the expensive
side, and the ~$0.01/page assumption every limit in this document rests on was
made against figures alone. It is now weaker still, which makes §4.3 more
overdue rather than less.

Retaining the raw page text was the cheap alternative and was refused: keeping a
deck's full text indefinitely is retaining substantially the whole document, and
contradicts the promise that *"what survives is the extracted claims and a
downscaled first-page thumbnail"* — the one made to the App Store questionnaire.

### A claim is one shape, stored in two tables

The comparable core of a claim is shared, because the Auditor's entire
function is comparing a slide claim against a spoken one and they must be
comparable. Unit and period are load-bearing, not decoration: *"most false
positives come from comparing figures that were never comparable."*

The locators differ and so do the lifecycles, so the storage is separate:

| Table | Locator | Retention |
| --- | --- | --- |
| `material_claims` | `material_id`, `page` | Until the user deletes the Material |
| `session_claims` | `session_id`, `offset_ms` | Undecided — task #29 |

One table with a source discriminator would be a simpler query and was refused for
that retention split: deleting a session would mean surgically removing some rows
from a store governed by another policy, which is where retention bugs live.

**Both claim kinds share one table, and a CHECK constraint keeps them honest.**
The Auditor reads them together — a panelist's ammunition for one slide is its
figures *and* its assertions — so a `UNION` at every read would be a poor trade
for two sets of nullable columns the database enforces anyway. The constraint is
written as one exhaustive disjunction rather than two implications, because two
implications permit an assertion that also carries a metric: a row no reader
expects and every reader would interpret differently.

**Two bounds live in the Pydantic type because a column enforces them, and
settling is one transaction.** Either would otherwise let one bad entry refuse
every claim on the deck, leave the material `extracting`, and be requeued to
fail identically while charging for each attempt.

| Bound | Why the column has it | What the type does |
| --- | --- | --- |
| Figure magnitude | `value` is `Numeric(20, 6)` — fourteen digits ahead of the point | Refuses past `MAX_FIGURE`; the adapter's drop path counts it |
| Control characters | A NUL is not valid UTF-8 to Postgres, and a PDF text layer can carry one | Strips them; the surrounding words are still the citation |

The difference in treatment is deliberate. A hallucinated magnitude makes the
claim wrong, so the claim goes. A stray byte does not — the slide still said
what it said, and only the byte is dropped. A quote that was *nothing but*
control characters then fails `min_length`, which is the right answer for a
citation citing nothing.

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

**Built 2026-08-16**, and until then the pipeline rendered a thumbnail on every
deck and discarded it while never deleting a source at all — so the one sentence
the privacy answer rests on was false in both directions.

Three things the implementation had to settle, each of which is a way the
promise could have been quietly broken:

| Ending | Source | Why |
| --- | --- | --- |
| `ready` | Deleted | The claims are the deck now |
| `failed` | Deleted | Terminal. The user re-uploads, so nothing will ever open that object again — keeping it retains a confidential document for no purpose |
| `pending` (requeued) | **Kept** | Still going to be read. Deleting here turns a rate limit into permanent data loss, which is the one mistake in this area with no recovery |

**The delete cannot be in the transaction that settles the material** — one is
Postgres and the other an HTTP call to a bucket. So the row commits first and
`purge_sources` runs after, with `source_deleted_at` doubling as the record and
the retry marker. A delete that fails leaves it null and the next pass tries
again; without that, one 503 leaves a confidential document in the bucket
permanently with nothing pointing at it and nothing to notice.

It runs at the *end* of every pass, whether or not a deck was read. At the start
it would be a promise that depends on another pass ever happening; only on
success it would never retry an idle failure. Failures are caught per material
rather than per batch, because one object the store will not part with must not
switch the guarantee off for everybody else — and the partial index the query
runs on is the standing signal, since a successful delete drops the row out of it.

**The thumbnail is written before the model call**, not on success. It costs
about twenty kilobytes and it is the difference between a failed upload the user
recognises and a grey rectangle. Object first, row second: the other order would
record a key pointing at nothing the moment a write failed, which is a broken
image on every screen showing that material and one nothing would ever retry.

**The thumbnail is reachable as of 2026-08-16.** `MaterialRead` carries a
`thumbnail_url` — a short-lived presigned GET, signed per read and null until
there is something to show. Kept and unreachable is the same as not kept: the
material list would have shown a grey rectangle for a document whose only
surviving likeness was sitting in the bucket.

It is signed rather than streamed, for the same reason nothing else here is
proxied. `thumbnail_key` stays off the wire alongside `storage_key`, and the
signing lives on the service rather than in the handler — a route holding a
storage client is one step from signing the source key with it, which is the
single mistake in this area that hands out a confidential document. There is a
test that the URL reaches the thumbnail and not the deck, and it fails when that
substitution is made.

Still present on a `failed` material, deliberately. That is the state whose
answer is *"upload it again"*, which needs the user to know which of four files
to go and find — and `filename` alone is `deck-final-v3.pdf`, twice.

### The user can destroy a material, and the claims go with it

`DELETE /v1/materials/{id}` → 204. **Built 2026-08-16.** Until then
`material_claims` said claims were kept *"until the user deletes the Material"* —
a retention rule describing an action no endpoint offered, which is the worst
kind: it reads correctly and is unenforceable.

Both objects go, and so do the claims. By deletion time the claims *are* the
deck — the source is already gone — so keeping the figures out of somebody's
unannounced board deck after they asked for it to be destroyed would be the same
disclosure one step removed. `material_claims` and `session_materials` cascade
off the row; `extraction_costs` does not, because it has no foreign key precisely
so *"upload, extract, delete, repeat"* cannot erase its own trail.

**The row is marked, not dropped, and it survives the request by seconds.** The
mark commits first because it is what makes the material vanish from every read,
every claim query and every room — the parts of the promise this process can
guarantee on its own. The objects are deleted after, outside that transaction,
because a bucket cannot join one. A delete that fails therefore leaves a row the
sweep retries rather than a material that is gone from the API and present in
storage.

Two questions the window exists to answer, both resolved 2026-08-16:

**A deck deleted while it is being extracted.** Not a rare case — *"I uploaded
the wrong deck"* is the most likely deletion there is, and it lands squarely
inside the seconds a worker has the file open. Refusing until extraction finished
would have meant telling a user to wait up to fifteen minutes to destroy their
own document. Instead the worker asks, between opening the file and spending
anything on it, whether the material survived; if not it releases the claim and
the same sweep pass purges the row. Without that check it would render a
thumbnail into a bucket the user has just been told is empty — an object with no
row pointing at it, which nothing would ever find to clean up.

**A worker that has already paid.** `purge_deleted` skips materials in
`extracting` for the mirror-image reason: a model call that has been billed still
owes an `extraction_costs` row, and dropping the material out from under it loses
that row. Unrecorded spend on a deck nobody can see is exactly the abuse the
table exists to make visible. It finishes; the next pass takes the row.

**Refused while a room is still standing on it** — 422 `material_in_use`. The
Auditor cross-checks live speech against these claims, so removing them
mid-interrogation leaves somebody paying metered minutes for a panel that has
quietly stopped being able to catch anything, with nothing on screen saying so.
The refusal is bounded and the user holds the thing that ends it: a session is
capped at twelve minutes. This is the one refusal in ingestion that protects a
session rather than a file.

Ingestion asks `sessions` that question through `room_still_standing_on`, the
mirror of `confirm_ready` going the other way — each module reads its own tables
and neither reaches across. The dependency is genuinely mutual, so the import is
function-local; that is the containment, and it costs a dict lookup per deletion.

The deletion writes an `audit_events` row — the first in this module, and the
one place the argument is unanswerable: a promise to destroy a document is
unfalsifiable without a record that the user asked and we acted, and that record
has to outlive the thing it describes.

### Extraction cost is recorded, and page throughput is capped

An `extraction_costs` table keyed by `material_id` and `user_id`, recording
provider, model, pages and token counts.

Session-scoped `session_costs` cannot hold this. The metering boundary is locked —
only live interrogation is metered — so **extraction is a real per-user cost with
no revenue attached**, and the abuse case is precisely a deck that is extracted and
never becomes a session. Attributing cost to the session that used the material
would leave exactly that case invisible.

**One row per attempt, not per material.** A stalled `extracting` row is
requeued by design, and a requeue is a second invoice — a table keyed on
`material_id` would either refuse the second row or overwrite the first, and
both under-report money already spent.

**No foreign key to `materials`, which is the one place this departs from
`session_costs`.** Materials are user-deletable, so a cascading delete would let
"upload, extract, delete, repeat" erase its own trail: the abuse case above
would be the one shape of usage leaving no record. Same reasoning as
`audit_events` — a row must survive deletion of whatever it describes.

`tier` is denormalised onto the row for the reason `session_costs` denormalises
it: cost analysis groups by tier, and reading it live would re-price every past
extraction the moment somebody upgraded. It is also the number that answers
whether the free tier's page cap is set anywhere near right.

Three counters ride along on the same row, because it is the only per-attempt
record there is to hang them on. `claims_recorded` over `pages` is the
cost-per-claim §4.3 needs. `claims_dropped` is a deck grounding less than it
appears to. `pages_corrected` — how often the text layer disagreed with the
model's page — is the only measure of how far the model's own page attribution
can be trusted, and the number that should decide whether a page stays the
locator at all.

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

DAILY_PAGE_CEILING = 600          (Settings, uniform, rolling 24h)
```

The first two live in `billing/tiers.py` beside `MAX_UPLOAD_BYTES`, because they
are per tier and therefore pricing. The daily ceiling lives in `Settings`
because it is not: it is a circuit breaker in the same category as §4.7's
per-account daily spend ceiling, and putting it in the tier table would make it
read as an entitlement somebody bought.

**The daily ceiling may never fall below the largest per-file cap, and it
originally did.** Corrected 2026-08-16 from 200 to 600, once the sweep made the
limit real enough to check: pro sells 300 pages per file, so at 200 a user who
re-exported their deck to fix a typo had the second upload held for
twenty-four hours. An ordinary act, read as a runaway.

The mistake was calibrating a circuit breaker against *typical* use — the
40–80 pages a month this document estimates elsewhere — when the whole reason
pro carries a 300-page cap is that some users are not typical. A breaker belongs
far above peak legitimate use and far below the point where money is being lost.
`test_material_limits.py` holds the invariant, because the two figures live in
different files by design and nothing else would notice them drifting apart.

**It only ever fires at pro**, and that is not a defect. Free's hundred lifetime
pages sit below it outright and starter's whole month is six hundred, so on
those tiers the monthly budget reaches a runaway first — a cheaper limit doing
the job sooner, which is the order these four controls should fire in.

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

### Exceeding a limit does two different things, and the difference is a window

Every refusal here is a typed 422. What happens to the material afterwards
depends on whether waiting could ever help:

| Limit | Material becomes | Because |
| --- | --- | --- |
| Max upload bytes | *nothing — refused at the presign* | Checked before a row exists, so there is nothing to leave behind |
| Max pages per material | `failed` | **Terminal.** No window rolls over into a file being shorter |
| Monthly page budget | `pending` | A window. It extracts when the period resets |
| Daily page ceiling | `pending` | Same, on a shorter clock |

**Corrected 2026-08-16**, while building `parsing.py`. This section previously
said a material *"stays `pending` rather than failing, so it extracts when the
window rolls over"* without qualification — true of the two budgets, and wrong
for the per-file page cap, where it would leave a four-hundred-page deck on the
free tier being claimed by the sweep forever, failing identically every time and
charging for the attempt.

So they are separate errors rather than one. `MaterialTooManyPages` carries the
count and the limit, because the user has to send a smaller file and *"too long"*
without a number does not say how much smaller. The budget refusal says nothing
about file size, because the file is fine and the timing is not.

Two rules that follow, both of which fail quietly if forgotten:

- **A budget refusal must not consume a claim attempt repeatedly.** A material
  left `pending` under an exhausted budget is picked up by every sweep pass until
  the window rolls, so the check belongs in the claim query rather than after it.
- **Neither refusal charges for the pages it did not extract.** `extraction_costs`
  records work performed; a material refused before a model call has no row.

**Built 2026-08-16.** Both budgets are conditions inside the claim query rather
than checks around it, and the second reason for that turned out to matter as
much as the first: a check *after* the claim would let one user with nothing
left sit at the head of the queue being picked and declined on every pass,
stopping extraction for everybody.

The window is the account's own entitlement period — `period_ends_at` minus
`PERIOD_LENGTH`, the same clock the minutes allowance runs on, not a calendar
month. A null `period_ends_at` means a tier that never renews, and the absence
of a lower bound is exactly what makes the free budget lifetime. A stale
boundary (one passed, with `ensure_current_period` not yet run for that account)
widens the window rather than narrowing it, so the error is a deck that waits
rather than a budget that overspends, and the next thing that touches billing
repairs it.

**The overshoot this accepts.** The budget is compared against pages *already*
billed, and a deck's own page count is not knowable until it has been parsed —
so a user one page under can extract a full deck and land over. It is bounded by
`MAX_PAGES_PER_MATERIAL`: 300 against a 1200-page budget at the top rung, 20
against 100 on free. Closing it exactly would mean parsing every deck before
deciding whether it was allowed to be parsed. Reopen it if measured
`extraction_costs` show the overshoot is a real share of spend rather than a
rounding error.

Two failures reach the same terminal ending as the page cap, and for the same
reason — no window rolls over into them:

| Failure | Ending |
| --- | --- |
| The stored object is gone | `failed`. A HEAD at the handshake makes it rare, but waiting cannot bring back a deleted object |
| The file will not parse | `failed`. A corrupt or password-protected PDF does not repair itself |

---

## Modules

```
backend/app/core/
  storage.py            ObjectStorage protocol
  storage_s3.py         S3-compatible implementation (RustFS in dev)

backend/app/modules/ingestion/
  router.py             thin: presign, complete, read, delete
  service.py            material lifecycle, claim persistence, page budgets
  extractor.py          the sweep pass — release stale, claim, read, end
  runner.py             the loop that runs it, separate from the billing sweeps
  parsing.py            PDF/PPTX/image → rendered pages + text + exact
                        chart values where the format carries them (no model)
  extraction_model.py   ExtractionModel protocol
  extraction_models/
    __init__.py         build_extraction_model(settings)
    claude.py           first adapter
  models.py             Material, MaterialClaim, ExtractionCost ORM
  schemas.py            Claim, Unit, MaterialRead, MaterialState
```

**Renamed 2026-08-16 from `model.py` + `models/`, which Python cannot express.**
A package cannot contain both `models/` and `models.py`, and `models.py` already
holds the ORM. Named for the voice module's `provider.py` / `providers/` pairing
instead — same shape, no collision, and the parallel is the point: these are the
two vendor seams in the product and they should look alike.

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

**The structural half was built 2026-08-16** — `pptx_slides` in `parsing.py`,
behind `python-pptx`. Three things it settled that are easy to get wrong and
silent when you do:

- **Shape groups are walked into.** PowerPoint groups shapes whenever anybody
  selects a few and presses ⌘G, and a template's furniture usually arrives
  grouped. Reading only top-level shapes returns an empty slide for a deck full
  of text, with no error anywhere.
- **Table cells are read.** They are not text frames on the shape, so asking only
  for `has_text_frame` returns nothing for the densest page in the file — which
  is where a deck puts the numbers it is most confident about.
- **A gap in a chart stays a gap, in place.** Zeroing it says the quarter made
  nothing. Dropping it shifts every later value onto the wrong category, so a
  missing Q2 makes Q3's revenue read as Q2's — a figure that is exactly right and
  attached to the wrong period, which is how a false accusation gets made out of
  correct data. `ChartSeries.values` is positional against `categories` and that
  is the contract.

**The render half was built the same day**, once LibreOffice was installed, and
with it PPTX stopped being accepted at the presign and failed at extraction. That
gap — a real user-facing dead end, since a `failed` material is terminal and the
advice to re-upload produced the identical failure — is closed. `_parse` has a
PPTX branch and `parsing.py`'s type list now matches `ACCEPTED_CONTENT_TYPES`
exactly.

Four things the subprocess forced, each of which is a way it misbehaves:

- **Its own user profile per conversion.** LibreOffice serializes on a shared
  profile, so without `-env:UserInstallation` a second instance waits on the
  first — concurrent extraction silently becoming a queue, with nothing in a log
  to explain it. The profile lives in the per-conversion temporary directory and
  dies with it.
- **The exit code is not the signal.** `soffice` exits 0 on failures, so the
  output *file* is what gets checked. Trusting the return code turns a failed
  conversion into an empty deck reported as a success — and the source document
  is then deleted as though it had been read.
- **A timeout is terminal, not retryable.** Two minutes, generous because a cold
  container pays for the suite starting up. A hang is a property of these bytes,
  so the ten-attempt budget would spend an hour of worker time to reach the same
  answer.
- **The cap is checked against the slide count before converting.** Rendering a
  PDF is expensive; spawning an office suite is more so, and a cap applied after
  the fact is a bill followed by a refusal.

**Slide-to-page matching is positional, and guarded.** LibreOffice omits hidden
slides from the PDF, which would land slide three's chart on slide four's page —
a figure that is exactly right, cited against a slide the user never showed. When
the counts disagree the structural half is dropped rather than guessed at: the
cost is exact chart values on an unusual deck, against a panelist confidently
quoting the wrong slide, and `docs/auditor-grounding.md` rates those nowhere near
each other.

The exact values reach the model as their own content block per page, marked
exact, beside the image and the text layer — with gaps written as *"no value"*
rather than collapsed, so the alignment the parser protects survives being
written out. Without that block the second read would be dead weight and the
model would be back to reading bar heights.

The test decks are generated by `tests/pptx.py` rather than committed, which
carries one honest limit: they are written with the same library that reads them,
so a mistake in how `python-pptx` interprets the schema would be invisible. The
first deck saved by PowerPoint itself belongs in `tests/` as a fixture.

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
- **Panel setup.** `SessionStart` carries material ids and nothing else.
  Archetype selection and audience context belong with the panel work, and
  inventing those fields now would be guessing at a shape the interrogation
  design has not settled. The schema forbids extra fields, so a client sending
  one is told rather than silently given an ungrounded room.
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
- **PPTX has never been tested against a deck PowerPoint saved.** The test decks
  are generated by `tests/pptx.py`, so the schema is exercised through the same
  library that writes it, and LibreOffice's font substitution is exercised
  against fonts that were never chosen. The first real deck belongs in `tests/`
  as a committed fixture, and the first one converted in anger should be looked
  at rather than trusted.
- **The page budgets are enforced but not surfaced.** All four controls now have
  teeth (2026-08-16), but a material held back by a budget is simply not claimed:
  it stays `pending`, indistinguishable through the API from one that is merely
  next in line. Nothing tells the user *"this extracts when your period resets"*.
  That is a product decision about what a waiting material says, and it belongs
  with the setup screen rather than with the sweep — but it should not ship
  without an answer, because a deck that appears stuck forever is a support
  ticket either way.
- **There is no way to list materials.** A material is reachable only by its own
  id, so a client that lost track of one — a reinstall, a second device — cannot
  find it again, and the thumbnail now has nowhere to be shown at scale. It is a
  small endpoint and it waits on a product answer rather than a technical one:
  what a material list is *for* (picking grounding for the next room, or managing
  what is stored) decides whether it is filtered to `ready` and whether it
  paginates.
- **Only deletion is audited.** `MATERIAL_DELETED` is the module's one
  `audit_events` row, and the refusals are not: an oversized file, an unreadable
  type, a material that is not ready. Each is a typed 422 the caller sees, and
  none of them changes anything worth proving later — but the line between "worth
  an audit row" and "worth a log line" here is currently *"deletion, because a
  privacy promise must be provable"* rather than a considered rule. A budget hold
  is the case that will decide it: it is neither a refusal nor a request, just a
  row the claim query passed over, and the honest answer to *"why did this deck
  wait"* would be an audit row written the first time a material is declined.
  This paragraph previously claimed every refusal wrote one, which was never
  true of any of them.
- **Per-seat accounting for Teams is unspecified.** The budget is written per
  seat, and nothing yet says whether an unused seat's pages pool across the
  organisation. It does not block anything until Teams ships.
