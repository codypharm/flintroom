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

## Start from `backend/`

`Settings` reads `.env` relative to the working directory, and the scripts
resolve it the same way. Real environment variables take precedence, so a
deployment that sets them properly needs no file — but a process started from
the repository root with only a file to read will boot with nothing configured
and fail on the first request that needs a secret.

## Still open

- **Recording retention is undocumented and unimplemented.** App Store review
  will ask, and `Product.md` §7 week 8 puts the privacy policy on the critical
  path. Nothing is being retained today because no transcript is stored, but
  that stops being true the moment the Auditor lands.
- **`ELEVENLABS_API_KEY` is a personal, account-scoped key** — task #12. It can
  read every conversation transcript and spend the balance. Blocked until the
  plan is paid, and a launch blocker rather than a nice-to-have.
- **No health endpoint.** Nothing here needs one yet; a load balancer will.
