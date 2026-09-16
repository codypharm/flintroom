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

**Point an external monitor at `GET /health/sweeps`. Built 2026-08-24.**

Billing is a sweep loop inside every API process (`sessions/runner.py`). If
every process running it is down, nothing bills — while the voice provider
carries on charging us for rooms that are still open. Ticks are charged in
arrears, so no user is ever overcharged by this; the entire loss is ours.

Nothing raises when this happens. A stopped loop emits no error, produces no
failed request, and leaves no trace beyond the line it is no longer writing.
`/health/sweeps` exists to turn that absence into something pollable: the
runner stamps a heartbeat each time the **meter sweep succeeds** — not each
time the loop survives a pass, because a loop alive with a broken meter is
exactly the silence being watched for — and the endpoint returns 500 once the
silence exceeds `METER_SILENCE_LIMIT` (120s, eight missed passes), or when the
process has no runner at all. It is deliberately separate from `/health`:
Railway restarts a container whose healthcheck fails, and restarting the API
does not revive the database the meter could not reach, so folding this into
liveness would turn a database blip into a restart storm on top of it.

The watcher is a free external uptime monitor (BetterStack or UptimeRobot)
polling `https://flintroom-production.up.railway.app/health/sweeps` every few
minutes, alerting to email and the monitor's phone app when it sees a non-200.
The monitor's own confirmation delay (two failed polls before alerting is
typical) sits on top of the 120s, which is the tolerance for pooler restarts
working as intended. With more than one replica the monitor sees whichever
container the edge routes it to — fine at this scale, since each replica runs
the same loop against the same database, and a database-side failure stalls
all of them at once.

`meter_swept` is still logged unconditionally on every pass, empty ones
included, and remains the greppable record of what the endpoint judges.
`sweep_pass_failed` firing repeatedly is the milder version — the loop is
alive but cannot reach the database.

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

  Since #72 the same line is also emitted *per request*, from
  `IngestionService._storage`, whenever something actually reaches for the
  bucket. Deliberately the same spelling — an alert that matched only the
  startup line would miss every attempt made afterwards — so expect a burst
  rather than one occurrence, and read the startup line as the cause. Reading
  the upload limits no longer produces one at all: that call stops at the
  database, and it is the one ingestion endpoint that still answers during an
  outage.
- `room_recording_failed` — a room finished and its audio could not be encoded
  or stored. Nothing is retried: the mixer's buffer died with the socket, so
  the recording is gone for good. Unlike the material line above, no user has
  been told anything, so this is a quality signal rather than a broken promise —
  but a *rate* rather than a one-off means playback is broadly not working.

The lifecycle rule on the bucket is a backstop for the first of these and must
stay generous enough never to be the thing doing the work. If rooms are
disappearing at Pro's window plus the margin rather than at Pro's window, the
sweep is dead and the backstop is covering for it.

**Alert on the absence of `account_deletions_swept`, and rank it above all
three.**

Account deletion rides the same loop as a sixth sweep and logs one line per
pass, empty ones included. Every other silence here costs money, time, or a
retention promise. This one means **people who asked to be forgotten have not
been**, on a timetable the app told them in writing — and unlike a retained
recording, nobody outside can observe it, because the account already looks
deleted to the person who asked.

`purged=N` is how many accounts the pass destroyed. Zero is the ordinary
reading and is not a problem; it is the *line* that has to be there.

Two more, in the same area:

- `account_purge_failed` — one account could not be purged, almost always
  because the object store refused a key. The purge is all-or-nothing, so
  nothing was destroyed and the account is met again next pass. A one-off is
  self-healing; the same `user_id` repeating means a deletion is stuck, and the
  seven days the user was promised are passing.
- `DeletionSweepUnconfigured` in a `sweep_failed` traceback — the loop was
  handed no object store. The sweep refuses rather than running the half it
  can, because the rows it would destroy are the only ones that know an object
  exists. Same startup cause as `object_storage_unconfigured` above, and the
  same thing to check first.

There is no bucket-lifecycle backstop for this one and there cannot be: what
runs late here is not the removal of an object on a schedule, it is a decision
about which objects to remove at all.

## Migrations run before the new version serves

Alembic reads `DATABASE_URL` from the environment, never from `alembic.ini`
(`migrations/env.py`). Every migration is backwards-compatible with the
previously deployed version by rule, so migrate first and deploy second; a
rolling deploy has both versions live at once regardless.

**When that variable is unset, Alembic does not fail — it migrates
`flintroom_test`.** `migrations/env.py:54` supplies a default, and the default
is the test database. So `alembic current` and `alembic upgrade head` both
succeed, report `(head)`, and leave the database you meant to migrate untouched.
Nothing in the output distinguishes the two.

Always set it explicitly:

```sh
export DATABASE_URL=$(grep '^DATABASE_URL' .env | cut -d= -f2-)
uv run alembic upgrade head
```

Found on 2026-08-18. `alembic current` reported head while `flintroom_dev` was
twelve migrations behind at `b8f134e09de3`; the first Google sign-in on Android
got a verified token, reached the account insert, and died on
`column "deletion_requested_at" of relation "accounts" does not exist`. The app
surfaced it as "That did not go through", which is correct behaviour and says
nothing. Confirm against the schema rather than the version table when a column
is missing — `alembic_version` is what the tool believes, not what is there.

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

> **CI installs it since 2026-08-22**, and the first run without it is what
> proved this section was not hypothetical: five PPTX tests failed with
> `FileNotFoundError: 'soffice'` on a runner where everything else passed. They
> pass on a developer machine because a developer installed it once and forgot.


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

## What the app asks for is decided by plugins, so read the bundle

Added 2026-09-04, after Play flagged `FOREGROUND_SERVICE_MEDIA_PLAYBACK` and
two rebuilds failed to clear it.

`app/android` and `app/ios` are generated and gitignored. EAS runs a fresh
prebuild from `app.json` for every build, so **a permission deleted from the
generated manifest is a change no build ever sees.** The first fix did exactly
that and shipped an identical bundle.

The permission was not in our config at all. `expo-audio`'s plugin adds
`FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_MEDIA_PLAYBACK` and an
`AudioControlsService` whenever `enableBackgroundPlayback` is left at its
default of *true* — a default that arrived with the library in #25 and that
nothing in the repo mentioned. `app/src/lib/app-config.test.ts` now pins the
option, because listing the plugin bare is enough to bring all three back.

**Verify against the artifact, not the config.** `expo config --type
introspect` reads the *existing* generated directories as its base, so a
stale local prebuild can make it agree with a build that does not exist. The
bundle is the only thing that cannot be wrong:

```bash
npx eas-cli build:list --platform android --limit 2 --json --non-interactive
curl -sL -o build.aab "<applicationArchiveUrl>"
unzip -p build.aab base/manifest/AndroidManifest.xml | strings | grep permission
```

The AAB's manifest is protobuf, but permission names survive as plain strings.
Measured this way: version 15 carried both permissions and the service;
version 16 carried none.

**A Play declaration outlives the bundle that caused it.** The console
evaluates artifacts still active in a track, and it re-scans on its own
schedule, so the warning persists for a while after a clean build is rolled
out. That lag is not evidence the fix failed — the bundle is.

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

## One project has several client IDs, and a token carries one

`GOOGLE_CLIENT_ID` and `APPLE_CLIENT_ID` are the `aud` values `OidcVerifier`
pins, and pinning them is the check that stops a genuine Google token minted for
somebody else's app from signing in here. Both accept a **comma-separated list**,
and Google needs one.

**Android's audience is the WEB client — measured, on 2026-08-18.** A real
sign-in on an emulator produced a token this backend verified against
`GOOGLE_CLIENT_ID=<web client>` and nothing else. That is what `webClientId`
means in the native SDK: *"the client ID of type WEB for your server"*. The
Android OAuth client authorises the app and never appears as an `aud`, so
listing it widens the pin for nothing.

**iOS is still unverified.** The iOS SDK may address its token to the iOS client
rather than the web one, which would need a second entry — hence the list. Do
not add it pre-emptively. Decode a real iOS token's `aud` and add what is
actually there; a guess here is indistinguishable from a broken key.

**Identify the Web client by its TYPE, not its label.** Ours was recorded as the
web client and was actually a native one, and the whole of one session went into
that. Google's own error is unhelpfully phrased as a server-side complaint —
`Auth: [GetTokenResponseHandler] Server returned error: You must use a Web client
as the server client ID` — which reads like the backend is at fault when the
value is set on the phone. Check a client's type without the console by asking
the authorization endpoint for an `http` redirect:

```sh
curl -sL "https://accounts.google.com/o/oauth2/v2/auth?client_id=<id>&redirect_uri=http%3A%2F%2Flocalhost%3A9999&response_type=code&scope=openid" | grep -oE "redirect_uri_mismatch|invalid_request"
```

A **Web** client answers `redirect_uri_mismatch` — it accepts the form and only
objects to the unregistered URI. A **native** client answers `invalid_request`;
it will not take an `http` redirect at all.

**Why widening is safe when it is warranted.** Every entry is a client in our own
Google project, so a token minted for our iOS app is exactly as trustworthy as
one minted for our web client. A stranger's client ID is still not in the set,
which is the entire attack the pin exists to stop. It is also Google's own
guidance for backend verification: compare `aud` against your client IDs, plural.
Warranted is the operative word — an entry that can never be an `aud` is not
defence in depth, just a larger set.

**Apple is different, and the trap is inverted.** A *native* Sign in with Apple
addresses its token to the app's **bundle identifier** — `com.flintroom.app` —
not to a Services ID. Services IDs belong to the web flow, which this product
does not have. Set `APPLE_CLIENT_ID` to a Services ID and every Apple sign-in
fails audience verification with an error indistinguishable from a broken key.

**Android additionally needs its own OAuth client registered in Google Cloud with
the signing SHA-1**, even though that client ID is passed to neither the SDK nor
this backend. Without it the native flow returns `DEVELOPER_ERROR`, which is
another message that names nothing.

**Android additionally needs its own OAuth client registered with the signing
SHA-1**, and the debug fingerprint comes from the keystore Gradle generates
rather than from `~/.android`:

```sh
keytool -list -v -keystore app/android/app/debug.keystore -alias androiddebugkey -storepass android
```

Without that registration the native flow returns `DEVELOPER_ERROR` *before any
UI appears*. That is also how to tell the two failures apart: if the account
chooser opens at all, the SHA-1 is fine and the problem is the audience.

Found on 2026-08-18, when the configured Google audience matched neither the
app's web nor its iOS client. Nothing failed at the time: there was no sign-in
screen yet to fail. Closed the same day, with a real Android sign-in reaching
`grant_free +900`.

## Minutes are given by script, never by SQL

A promo, the closed-test cohort, a complaint made good: all go through
`scripts/grant_minutes.py`, which writes a `grant_admin` entry with the operator's
name on it. Editing `accounts` in the Supabase SQL editor leaves a balance the
ledger cannot explain and the reconciliation test cannot see.

```sh
railway run uv run python -m scripts.grant_minutes \
    --file promo.txt --minutes 30 --campaign launch-week --operator nonso --dry-run
```

For one person, use `--email` instead of `--file` (repeatable).

**Granting to a list**, from `backend/`:

1. **Write the file.** One address per line. Blank lines and lines starting
   with `#` are ignored; case, surrounding spaces and duplicates do not matter.
   Keep it outside the repo, since it is a list of people's email addresses.

   ```text
   # launch week, sign-ups from the waitlist
   ada@example.com
   Ben@Example.com
   ```

2. **Pick a campaign name** that says what this is: lowercase, digits and
   hyphens, e.g. `launch-week`. Each person gets one grant per campaign name,
   ever, so a new promo needs a new name.
3. **Dry-run** (the command above). Check the `database:` line names the
   production host, not `localhost`, and read the four lists: *would grant*,
   *already had this campaign*, *no account with this verified address*, and
   *address on more than one account*.
4. **Run it for real**: the same command without `--dry-run`.
5. **If it stopped partway**, run the identical command again. Anyone already
   granted moves to *already had this campaign* and is not paid twice.
6. **The skipped addresses are yours to resolve.** *No account* usually means
   they have not signed up yet, or signed in with a different address (Apple's
   Hide My Email is the common one). Once fixed, re-run the same campaign and
   only they are granted. *More than one account* cannot be granted by this
   script at all, since it finds people only by address; it is rare (it needs
   two sign-ins that failed to link) and worth asking about before building
   anything for it.

Minutes per person are capped at 600, as a typo guard.

Gifts land in the top-up bucket (they never expire) under their own reason, so
§4.5's upgrade rule never counts one as a purchase.

**Who can run it is whoever holds the production database URL**: members of the
Railway project, members of the Supabase project, and anyone that URL was pasted
to. No endpoint reaches it, and the code alone connects to nothing. The script is
not the boundary, since that same group could edit balances in the SQL editor;
membership is. Keep both projects to people trusted with money, and rotate the
database password when one of them leaves. `--operator` is attribution, not
authentication: it records who says they ran it.

**Do not run `scripts/dev_token.py` against production.** It creates accounts
under a `dev:` subject, so it would not find a real user, and its stale-room
release fails every open room in the database, not only that user's.

## Still open

- **Recording retention is undocumented and unimplemented.** App Store review
  will ask, and `Product.md` §7 week 8 puts the privacy policy on the critical
  path. Nothing is being retained today because no transcript is stored, but
  that stops being true the moment the Auditor lands.
- **`ELEVENLABS_API_KEY` is a personal, account-scoped key** — task #12. It can
  read every conversation transcript and spend the balance. Blocked until the
  plan is paid, and a launch blocker rather than a nice-to-have.


---

## On Railway

Decided 2026-08-23, on cost: Supabase's free tier hosts Postgres (the locked
CLAUDE.md decision, unchanged), Railway Hobby runs the one container, R2 holds
the objects — about $5 a month all-in, with the exit staying a `pg_dump` and a
connection string because nothing below uses a feature only Railway has.

**The pieces in the repo.** `backend/Dockerfile` builds the image (uv pinned to
the version developers run; LibreOffice installed for PPTX; PyAV brings its own
ffmpeg). `backend/start.sh` is the serving process. `backend/railway.json`
tells Railway to build the Dockerfile, to health-check `GET /health`, and to
run migrations as `preDeployCommand`.

**Migrations run once per deploy, not once per container.** `start.sh`
deliberately does not migrate: with more than one replica it runs N times per
deploy, and N containers racing `alembic upgrade head` is a lock pile-up at
best. Railway's `preDeployCommand` runs exactly once, before any new container
serves — which is also what the backwards-compatibility rule above assumes.
Note it inherits the service's environment, so `DATABASE_URL` is set and the
test-database default in `migrations/env.py` cannot bite.

**`FORWARDED_ALLOW_IPS` is required, has no default, and must not be `*`.**
`start.sh` refuses to boot without it — the reasoning is the first section of
this document. On Railway the peer is their edge proxy on the private network:
observed on the first deploy (2026-08-23) as `100.64.0.2`, so the variable is
pinned to `100.64.0.0/10` — the carrier-grade-NAT range Railway's proxy lives
in, unroutable from outside, and wide enough to survive the proxy moving
within it. If a future deploy logs a peer outside that range, re-derive it
from the logs the same way rather than widening toward `*`. Then check the
rate limiter keys on real client addresses by signing in twice from two
networks.

**The database URL is Supabase's session pooler, not the direct connection.**
The free tier's direct connection is IPv6-only, and the pooler speaks IPv4 on a
different host and port — copy the *Session pooler* URI from the dashboard and
swap the scheme to `postgresql+asyncpg://`. Session mode, never transaction
mode: asyncpg's prepared statements do not survive a transaction-mode pooler.
Create the project in `us-east-1` and put the Railway service in US East — the
turn path makes many trips to the database and the AI providers, and one trip
to the phone.

**Environment variables, by name** (values live only in the dashboard, and
task #12 rotates every one of them before this service goes public):
`DATABASE_URL`, `JWT_SECRET`, `GOOGLE_CLIENT_ID`, `APPLE_CLIENT_ID`,
`ELEVENLABS_API_KEY`, `GEMINI_API_KEY`, `REVENUECAT_WEBHOOK_SECRET`,
`S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET`,
`FORWARDED_ALLOW_IPS`, and — once the domain is verified in Resend —
`RESEND_API_KEY` with `EMAIL_FROM` (both or neither; a half-configured pair
refuses at boot). `PORT` is Railway's own.

**Deploys are gated on CI.** Connect the repo with the service's root directory
set to `backend/`, and enable *wait for CI* on the service so a push to `main`
deploys only after the checks below are green. CI stays integration-only —
nothing in it holds a deployment credential; Railway pulls, it is not pushed
to.

**Scaling is the replicas dial, and the app was shaped for it.** One asyncio
worker per container; more capacity is more replicas, not more workers. The
write path locks per user and holds nothing global (`docs/deferred-scale-work.md`),
every replica runs its own sweep loop by design, and a live room's WebSocket
pins to whichever container accepted it for the life of the socket. The two
things that do not multiply with replicas: migrations (see above) and the
database's connection budget — the free-tier pooler is the ceiling to watch
when the dial goes past a handful.

**The healthcheck is liveness and nothing more.** `/health` touches no
database and no provider, deliberately: a check that hits a dependency turns
that dependency's blip into a restart storm on top of it. The smoke test for
this shape is in the container's own behaviour — booted against an unreachable
database it stays up, answers `/health`, and logs `sweep_failed` until the
database returns — which `/health/sweeps` and the monitor watching it exist
to notice, not the restart policy.

---

## What CI enforces, and what it deliberately does not

`.github/workflows/ci.yml`, added 2026-08-22. **Integration, not deployment** —
where this ships is undecided and that file does not decide it: nothing in it
builds an image, pushes an artefact, or holds a deployment credential. What it
replaces is a state where every check ran only when somebody happened to run
one, which made "the suite is green" a statement about a person rather than
about the repository.

Two jobs, six checks: `pytest` and `uvx ty@0.0.73 check app` on the backend,
`tsc --noEmit`, `eslint` and `jest` on the app, and one drift check described
below.

**Lint fails on errors and not on warnings**, which is eslint's default and the
right ratchet: there are still warnings in the tree, and a threshold pinned to
today's count would either age into noise or fail on a file somebody merely
moved. The rules that matter are React's own — `react-hooks/refs`,
`set-state-in-effect` and `purity` are what the React Compiler needs in order to
reason about a component, and this app has one screen that genuinely cannot
afford a dropped frame.

**`ty` is pinned there for the reason `pyproject.toml` gives.** It is
preview-stage, so an unpinned run can report differently on unchanged source and
"the checker is clean" would become a statement about the day. Its failure mode
is also why it belongs in CI rather than in a habit: diagnostics accumulate one
at a time, each individually ignorable, until nobody reads the output — which is
the state it started in, and the state in which it found a `None` being seated
in a live room and an annotation naming the wrong `Enum`.

**The generated client is checked against the contract.** `test_contract` proves
`contracts/openapi.yaml` matches the application. Nothing proved the committed
`app/src/lib/api/schema.d.ts` still matches that contract — and it is committed
on purpose, so a clone builds without running codegen. Both files live in the
repository, so either can go stale against the other with every test still
green. CI regenerates and fails on a diff.

**A run builds its own `.env` from `.env.example`**, and that is not only
plumbing. One test — `test_alembic_migrates_what_the_app_runs_on_when_nothing_says_otherwise`
— unsets `DATABASE_URL` and asserts alembic still resolves the application's own
database, which is #28's fix and is only provable when something other than the
process environment can answer. Building the file from the example also proves
that example is still complete enough to boot, which is the one property of it
nothing else checks and exactly the kind this document exists for: it fails
quietly, months later, on somebody's first clone. The signing key is generated
per run, so no credential-shaped string sits in the workflow.

**Postgres and MinIO come from `backend/docker-compose.yml`**, the same file a
developer uses, so there is one description of what the suite needs. A
filesystem stub was refused for the same reason `docs/ingestion.md` refuses one
in development: it cannot do direct-to-storage PUT without proxying, so it would
leave the presigned path untested until deploy.

**Still not covered, and worth knowing:** nothing runs Maestro, so the E2E flows
`CLAUDE.md` names as release gates are unenforced; nothing builds the app for
either store; and no deployment step exists at all, by design.
