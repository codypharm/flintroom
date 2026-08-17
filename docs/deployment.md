# Running the backend somewhere real

The requirements that are load-bearing but invisible — each one currently
enforced by a docstring somebody has to have read. Everything here is a
deployment decision rather than a code change, which is precisely why it needs
writing down: none of it fails a test, and most of it fails quietly.

Configuration itself is in `backend/.env.example`, which is the list of what
must be set. This is the list of what must be *true*.

## The proxy must rewrite the peer

**Start uvicorn with `--proxy-headers` and `--forwarded-allow-ips` set to the
load balancer's address. Not `*`.**

The rate limiter keys unauthenticated attempts on the socket peer and refuses to
read `X-Forwarded-For`, because that header is written by whoever is calling —
trusting it hands an attacker an unlimited supply of identities and makes the
limiter decorative (`auth/dependencies.py` → `_caller`).

The consequence is that behind a load balancer, the peer *is* the balancer.
Every user in the world then shares one bucket, and the sign-in limit becomes a
denial of service that any single client can trigger against everybody.

`--forwarded-allow-ips=*` restores the original bug with extra steps: it tells
uvicorn to trust the header from any source, including a caller that reached the
app directly. The address of the balancer, and nothing else.

This is the one item here that is a security control rather than an operational
concern, and it is the one most likely to be missed, because a deployment
without it looks completely healthy until it is attacked.

## Something must alert on silence

**Alert on the absence of `meter_swept`, at greater than one interval.**

Billing is a sweep loop inside every API process (`sessions/runner.py`). If
every process running it is down, nothing bills — while the voice provider
carries on charging us for rooms that are still open. Ticks are charged in
arrears, so no user is ever overcharged by this; the entire loss is ours.

Nothing raises when this happens. A stopped loop emits no error, produces no
failed request, and leaves no trace beyond the line it is no longer writing. So
`meter_swept` is logged unconditionally on every pass, empty ones included, and
the absence of it is the only available signal.

`sweep_pass_failed` firing repeatedly is the milder version — the loop is alive
but cannot reach the database.

**Alert on the absence of `extraction_swept` too, at greater than one interval.**

Extraction runs in a *second* loop (`ingestion/runner.py`), separate from the
billing sweeps because a pro-tier deck takes minutes to read and would stall the
meter if it shared a pass. It has the same silent-failure shape and the same
answer: one line per pass, empty ones included, and the absence of it is the
signal.

The consequence differs, though, and it is worth knowing which alert is which.
The meter stopping loses money quietly. Extraction stopping loses nothing and
charges nothing — uploads keep succeeding, materials pile up in `pending`, and
every session started against one is refused as not ready. It presents to users
as decks that never finish, and to us as nothing at all.

Two lines nearby that mean something specific:

- `extraction_sweep_disabled` at startup — the deployment has no bucket or no
  extraction key, so the loop was never started. Expected in an environment
  running without them; a defect anywhere material is meant to work.
- `material_extraction_released` — a deck was taken back from a process that
  stopped holding it. One after a deploy is the design working. A steady stream
  is a worker dying mid-read, and each one costs a re-extraction.
- `material_source_delete_failed` — **the one on this list that is a privacy
  matter rather than an operational one.** It means an uploaded deck is still in
  the bucket after the material stopped needing it. A single line is recovered
  automatically on the next pass; a repeating one means the retention promise
  made to the App Store questionnaire is not currently being kept, and the
  standing measure of the backlog is the row count matching
  `ix_materials_source_undeleted`.
- `material_delete_failed` — **the other privacy line, and the more serious of
  the two.** A user asked for a material to be destroyed and at least one of its
  objects is still in the bucket. The API has already told them it is gone, so
  unlike the line above there is a person who believes something that is not yet
  true. Recovered on the next sweep pass; repeating means it is not being
  recovered, and the backlog is the row count matching `ix_materials_deleted`.
  Alert on this one directly rather than only on the index size.

**Alert on the absence of `recordings_swept`, and treat it differently from the
other two.**

Retention rides the billing loop as a fifth sweep and emits one line per pass,
empty ones included. Its silence has a consequence the others do not: the meter
stopping loses money, and extraction stopping loses time, but this stopping
means **room audio is outliving the window published on the tier cards**
(`billing/tiers.py` → `RECORDING_RETENTION_DAYS`). That is a promise being
broken quietly, and `docs/session-retention.md` chose an application sweep over
a bucket lifecycle rule precisely so the deletion could be proved — which is
worth nothing if nobody notices the prover has stopped.

`expired=N` on that line is how many rooms the pass removed. A number pinned at
`BATCH` on every pass means the backlog is growing faster than one pass clears
it, not that everything is fine.

Two more, in the same area:

- `object_storage_unconfigured` at startup — no bucket, so the retention sweep
  is skipped entirely and `recordings_swept` never appears. Expected in a
  deployment that records nothing. **In one that does, this is the line that
  explains a missing sweep**, and the two are indistinguishable downstream, so
  check for it before concluding the loop died.
- `room_recording_failed` — a room finished and its audio could not be encoded
  or stored. Nothing is retried: the mixer's buffer died with the socket, so
  the recording is gone for good. Unlike the material line above, no user has
  been told anything, so this is a quality signal rather than a broken promise —
  but a *rate* rather than a one-off means playback is broadly not working.

The lifecycle rule on the bucket is a backstop for the first of these and must
stay generous enough never to be the thing doing the work. If rooms are
disappearing at Pro's window plus the margin rather than at Pro's window, the
sweep is dead and the backstop is covering for it.

## Migrations run before the new version serves

Alembic reads `DATABASE_URL` from the environment, never from `alembic.ini`
(`migrations/env.py`). Every migration is backwards-compatible with the
previously deployed version by rule, so migrate first and deploy second; a
rolling deploy has both versions live at once regardless.

## The application role is not a superuser

Every application table has row-level security enabled with a deny-all policy
(migration `1f359ab487a7`). This is defense-in-depth and deliberately does *not*
constrain the app: FastAPI holds the only credential in use, that role owns the
tables, and an owner bypasses RLS.

What it closes is the path that never goes through FastAPI — a leaked key, an
analytics role granted more than intended, PostgREST left enabled. Granting a
second role access to these tables silently defeats it only if that role is also
an owner or a superuser. Don't.

## The voice agent is configured by script, not by hand

`uv run python -m scripts.configure_agent --apply`, run from `backend/`, against
each ElevenLabs agent a deployment uses.

`CLIENT_EVENTS` in that script is authoritative and replaces the agent's list
wholesale. An event switched on in their dashboard and not written down there is
removed the next time the script runs — which is the intended behaviour, and the
reason the dashboard is not the source of truth.

Two settings in it are not cosmetic:

- `max_duration_seconds` sits deliberately *above* our own session cap. If the
  provider hangs up first, the relay reads it as a mid-room failure and settles
  as `provider_failure` — which refunds the whole session. Every ordinary room
  would look like an outage and cost us the minutes.
- Audio format must match on both legs. A mismatch arrives as noise rather than
  as an error.

## The material bucket exists, and is private, and the app cannot create it

**Create the bucket out of band. Do not grant the application `s3:CreateBucket`.**

Nothing in the code creates it — `docker compose` does that for development with
a one-shot `mc` container, and the equivalent in production is a console click or
a line of Terraform. A process that can create buckets holds that permission for
its entire life in exchange for one action taken once, and the failure it saves
you from — a missing bucket — is loud, immediate, and fixed in a minute.

The permissions the app actually needs are `s3:PutObject`, `s3:GetObject` and
`s3:DeleteObject`, scoped to that bucket's ARN. Nothing else. In particular it
never needs `s3:ListBucket`: every read is by key, and a credential that can
enumerate is a credential that turns one leak into every user's deck.

The upload handshake also issues a `HEAD` before it lets a material become
extractable, and **`HeadObject` is authorised by `s3:GetObject`** — there is no
separate head permission. A policy that grants `PutObject` and `DeleteObject` but
withholds `GetObject`, on the reasoning that the server never downloads anything,
breaks every upload completion. It surfaces as a 500 rather than as "we did not
receive that file" — `exists()` only reads a 404 as absence and re-raises
everything else, deliberately, so a permissions mistake cannot be reported to
users as their own upload failing.

**The bucket must not be publicly readable.** Every path in and out is a
presigned URL that expires in fifteen minutes, and a public-read bucket makes
that expiry decorative while looking completely correct from inside the app —
uploads work, downloads work, and the objects are also simply on the internet.
On AWS this means Block Public Access on at the account level; on R2, no public
`r2.dev` domain and no custom domain bound.

This is portable by construction rather than by intent: the code speaks the S3
API and holds no vendor SDK above `core/storage_s3.py`, so AWS S3, Cloudflare R2,
Backblaze B2 and a self-hosted MinIO differ by four environment variables. Weigh
egress when choosing — presigned GETs are served to phones, and that is billed
traffic on S3 and free on R2.

**`S3_ADDRESSING_STYLE=path` for anything without per-bucket DNS.** That is MinIO
locally and Cloudflare R2, which documents path-style. AWS S3 needs nothing: the
default is virtual-hosted, because AWS has said path-style URLs *"will be
discontinued in the future"* — a deprecation delayed indefinitely in September
2020 with a promise of a year's notice, so it works today and is still not worth
depending on.

Getting it wrong is loud and immediate rather than quiet: a virtual-hosted URL
against MinIO names a host that does not resolve, and the upload fails on the
first attempt rather than at some later scale.

## LibreOffice is in the image, or PPTX quietly stops working

The extraction sweep converts a PPTX to PDF by running headless LibreOffice as a
subprocess. It is the only system package this backend needs, and the only input
type that needs it — `apt-get install -y libreoffice` on Debian, `brew install
--cask libreoffice` locally. It is large, around 400 MB installed, and that was
accepted deliberately: the alternative was a hosted conversion API, which would
ship confidential decks to a third party and contradict the retention promise.

`LIBREOFFICE_BINARY` overrides the path if an image puts it somewhere other than
PATH. Leave it unset and it is `soffice`, which both packages provide.

**The failure is one-sided and quiet, which is what makes it worth a section.**
Without the binary, PPTX materials fail as unreadable while PDFs and photographs
carry on working perfectly — so nothing looks broken, no health check goes red,
and the only signal is `libreoffice_missing` in the logs with the path that was
tried. Alert on it.

Two more things this subprocess implies:

- **Temporary space, and briefly confidential temporary space.** The tool takes a
  path rather than a stream, so each conversion writes the deck and a private
  LibreOffice profile into a temporary directory and removes both on the way out,
  including on failure. Whatever `TMPDIR` points at is somewhere other people's
  unannounced financials exist for a few seconds — it should be local disk, not a
  shared volume, and not something backed up.
- **A conversion is bounded at two minutes** and a timeout fails the material
  terminally rather than requeueing it, because a deck that hangs the converter
  hangs it again. `pptx_conversion_timed_out` repeating means decks are being
  refused for a reason nobody is looking at.

## The panel can degrade without failing

**Alert on the ratio of `panel_turn chosen_by=fallback` to all `panel_turn`.**

Three things can choose who speaks, and they are not equally good:

| `chosen_by` | What it means |
| --- | --- |
| `finding` | The Auditor caught a contradiction and the domain that owns the figure took the floor. The best kind of turn there is. |
| `model` | The ordinary case. Reads the room, and can see a custom archetype a Pro user wrote this morning. |
| `fallback` | Keyword routing, because selection was late, failed, or named nobody. Measured at 53% relevance against realistic speech. |

**Nothing fails when this degrades**, which is the whole reason it needs an
alert. If the panel model starts erroring — a bad key, a rate limit, a provider
having an afternoon — the room carries on speaking. Transcripts still read
plausibly. Sessions still bill. The only difference is that every choice now
comes from a table that gets it roughly half right, and the panel is quietly
worse at the one thing it is sold for.

A baseline of a few percent is expected and healthy: it is what the fallback is
for. A sustained figure above ~20% means the model is not answering, and the two
lines that say why are:

- `panel_selection_failed` with a `reason` — the provider refused or was
  unreachable. `panel_model_refused` and `panel_model_unreachable` in the same
  window carry the status code.
- `panel_selection_unrecognised` with `chosen` — the model answered with a name
  nobody in the room has. A steady stream is a prompt that has stopped working,
  and the name it returned is the only clue as to how.

Neither is an error to the user, and neither will appear in an error rate.

`panel_routing_outrun` joins them, and means something different: the model was
answering, just not before the user stopped talking. Selection runs against a
partial transcript while somebody is still speaking, and an utterance shorter
than the call leaves the final arriving first. A few of these are ordinary —
short answers exist. A lot of them means either the panel model has slowed down
or `VAD_SILENCE_THRESHOLD_SECS` has been set too low to cover it, and the
symptom is the same as the ones above: a room that quietly routes by keyword.

`panel_routing_started` carries a `words` count and nothing else. It is there
because routing on two words and routing on twelve are indistinguishable in a
transcript, and `CLAUDE.md` forbids putting the text itself in a log line.

## How long a pause has to last is a setting, and it has no measurable floor

`VAD_SILENCE_THRESHOLD_SECS` decides when the transcription engine calls the
user's turn over. It sits **directly inside perceived latency** — 0.77s of a
~2.15s room at the shipped default of 0.7, the largest single term after
composition — so lowering it is the cheapest latency available.

It is a setting rather than a constant because nothing bounds it from below that
anyone can compute. Too low and the panel starts answering while somebody is
drawing breath mid-sentence, and a room that interrupts you cannot be argued
with — which is worse than a room that is slightly slow. Synthetic speech has no
mid-sentence hesitations, so no spike, no test and no scripted run can find that
floor. Only a person, in a real room, pausing the way people actually pause.

Measured end to end across five turns, everything else held constant:

| threshold | speech stops → caption | → first audio |
| --- | --- | --- |
| 0.7 (default) | 1.77s | ~2.15s |
| 0.4 | **1.47s** | ~1.85s |

The full 0.30s comes through, so the setting is very nearly the whole term and
the engine's own overhead is small. An earlier single-utterance probe suggested
only 0.12s; the five-turn run is the one to believe.

Unset means the adapter's default. Change it in `.env` and restart the backend —
nothing in the app needs rebuilding, so two values can be heard back to back in
the same sitting.

**Judged on a real phone, 2026-08-17, and this is the only kind of evidence that
counts here.** At 0.4 the panel interrupted a real person mid-answer. At 0.7 it
did not, and the room read as comfortable. The floor is therefore somewhere
between the two and 0.55 is untested; 0.7 ships until somebody sits with it and
says otherwise.

Worth stating plainly because the arithmetic points the other way: 0.4 is 0.30s
faster and every measurement said take it. A room that interrupts you cannot be
argued with, which is worse than a room that is slightly slow, and no
measurement was ever going to say that.

## The store's callbacks are the only unauthenticated write path

`POST /v1/webhooks/revenuecat` takes no token. The shared secret *is* the
authentication, which makes it the most valuable thing to forge in the API: it is
the endpoint that grants minutes.

Enable **HMAC signing** on the RevenueCat webhook integration and put the signing
secret in `REVENUECAT_WEBHOOK_SECRET`. The plain Authorization-header option
RevenueCat also offers is not supported here and should not be used — a static
header is replayable forever, and the HMAC covers a timestamp.

- **Unset, the endpoint refuses everything** with a 503 and records every
  refusal. Purchases stop being credited, loudly. The alternative — accepting
  what cannot be verified — is an open grant endpoint that looks healthy.
- **The route is absent from `contracts/openapi.yaml`** on purpose. That contract
  is what the app generates its types from, and RevenueCat is not our client.
- **A non-200 is retried five times** over roughly two and a half hours, and the
  connection is dropped after 60 seconds. Anything slow or flaky here turns one
  purchase into five deliveries.

**Alert on `webhook_rejected` in `audit_events`.** One is noise — a clock drifting,
a retry crossing a secret rotation. A burst is somebody working through guesses at
the secret, and it is the only warning there will be. The `reason` in the row
separates the two: `bad_signature` is a person, `stale_signature` is usually a
clock, and `unconfigured` means this deployment is dropping real purchases on the
floor right now.

## Start from `backend/`

`Settings` reads `.env` relative to the working directory, and the scripts
resolve it the same way. Real environment variables take precedence, so a
deployment that sets them properly needs no file — but a process started from
the repository root with only a file to read will boot with nothing configured
and fail on the first request that needs a secret.

**Only fields declared on `Settings` are read from that file.** This is not a
general dotenv loader: nothing puts `.env` into the process environment, so a
variable read through `os.getenv` will be present in the file and absent from
the process. `DATABASE_URL` was exactly that until it became a field, and the
symptom was the worst available one — the file said it was configured and the
process said it was not set. Anything new that belongs in `.env` belongs on
`Settings`.

Alembic is the remaining exception, and deliberately: `migrations/env.py` reads
the environment directly, so migrations do not require a signing key or a set of
OAuth client IDs to run. It follows that `.env` does *not* configure a migration
— export the variable, or pass `uv run --env-file .env`.

## The app is a factory, so serve it as one

```bash
uv run python -m uvicorn app.main:create_app --factory
```

`create_app()` is not a module-level `app`, because `configure_logging()`
replaces the root handlers and belongs to the lifespan rather than to anything
that runs on import. `uvicorn app.main:app` therefore fails with *Attribute
"app" not found*, which reads like a missing file rather than a missing flag.

## Still open

- **Recording retention is undocumented and unimplemented.** App Store review
  will ask, and `Product.md` §7 week 8 puts the privacy policy on the critical
  path. Nothing is being retained today because no transcript is stored, but
  that stops being true the moment the Auditor lands.
- **`ELEVENLABS_API_KEY` is a personal, account-scoped key** — task #12. It can
  read every conversation transcript and spend the balance. Blocked until the
  plan is paid, and a launch blocker rather than a nice-to-have.
- **No health endpoint.** Nothing here needs one yet; a load balancer will.
