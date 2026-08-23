# Reconnect — a dropped room's way back

Resolved with the architect on 2026-08-24 (task #100, grilled question by
question). Read this before touching the relay's `_end`, the meter's
`_live_rooms` join, the reaper's ACTIVE paths, `sessions.disconnected_at`, or
anything that opens or closes a `SessionPhaseSpan`.

The exhibit that created the task: a real room on the architect's phone died
mid-sentence, the server settled it as `client_disconnect` within a second,
and 81 seconds were charged to a session whose own `session_costs` row shows
zero STT seconds, zero TTS characters, zero transcript lines — a room that
demonstrably never heard a word. Two separate wrongs in one incident: no way
back, and money kept for a technical failure. This design fixes both.

## Vocabulary, first

**This feature is the *reconnect window*, never "grace".** Grace is already a
name in this codebase — `enter_grace`, `leave_grace`, `GRACE_CAP` — and it
means the bounded *overdraft* a room is allowed past a zero balance so the
panel can finish. Reusing the word for the disconnect window would make every
future search for either meaning useless, which is exactly the collision the
Domain Language section of CLAUDE.md exists to prevent.

## The five decisions

### 1. Disconnected-with-hope is a timestamp, not a sixth state

On an abnormal socket close the session **stays `active`** and gains a
`disconnected_at` stamp; it does not settle. The alternative — a named
`disconnected` state — was considered and declined because every query that
means "this user has a live room" would have to be found and taught about it,
and the one that was missed would be the bug. The worst miss is the
one-live-session lock (`uq_sessions_one_live_per_user`): a frustrated user
tapping Start during the window must be refused a *second* metered room, and
with the session still `active` the partial index enforces that with zero
changes. The product answer to that refusal is the app offering the way back
into the room that is waiting — never a paywall, and never a new room.

The clock's owner is the sweep loop, which already runs server-side in every
API process regardless of whether any socket exists. The window is
**30 seconds** (`RECONNECT_WINDOW`) — two sweep passes; long enough for an
app relaunch and a sign-in restore, short enough that a genuinely gone user
is not holding their own lock hostage.

### 2. The window is unbilled, and the window is the only bound

Nobody is interrogated in a tunnel. Charging for the gap would be billing for
dead air — the thing the metering rules exist to never do. The farming case
was examined and does not survive contact: killing your connection buys 30
seconds in which the room asks nothing and teaches nothing, then costs real
seconds of socket re-establishment. There is no free interrogation to
extract, so there is no daily quota, no counter, and no extra rule. The daily
spend ceiling already bounds the pathological account.

### 3. Resume is a re-minted ticket, the newest socket wins, and the room is rebuilt from the database

- **Re-mint, never bypass.** `POST /v1/sessions/{id}/stream-ticket` —
  authenticated, owner-checked — mints a fresh single-use ticket for any
  session of the caller's that is still `active`. The phone then connects to
  the same socket route as the first connect. Tickets stay single-use and
  30-seconds-lived; reconnection exercises the auth path the first connect
  already proved, rather than growing a second one.
- **"Still `active`", deliberately not "stamped `disconnected_at`".** The
  server can be *behind* the phone in noticing a drop: a phone that loses
  network often leaves a half-open socket the server discovers only when a
  write fails. A resume gated on the stamp would refuse exactly the fastest
  recoveries. So the mint requires only ownership and liveness, and a new
  connection for a room whose old socket has not died yet **supersedes** it.
- **Nothing about the room lives only in one process's memory.** Seats,
  claims, audience and the transcript are already read from the database at
  connect; resume is the same build plus replaying the transcript into the
  panel's context. This is what makes a reconnect that lands on a different
  container — a deploy mid-room, a second replica someday — identical to one
  that lands on the same container, which is the property
  `docs/deployment.md` says scaling depends on.

### 4. The room speaks first on resume

A presenter back from a tunnel does not know whether the room heard their
last sentence. Silence at that moment kills the illusion the product protects
everywhere else, so the room re-engages — and there are two gaps to cover,
told apart by whose turn the transcript says it was when the line dropped:

- Dropped while a **panelist was asking**: the same panelist re-delivers the
  outstanding question. The text is already in the transcript (a panel line
  is recorded before it is spoken), so this is re-synthesis, not a model call.
- Dropped while the **presenter was answering**: the panelist holding the
  floor gives a short hand-written re-entry line ("You dropped out
  mid-answer. Go on.").

Re-entry lines are authored per shipped archetype beside `openers` and
`nudges` — no model call, no latency, and no new prompt surface for user text
to reach, so the fencing rules are untouched. The panel says exactly one line
about the disconnect and never scores it: **a question left unanswered
because the line died must not rank in the debrief as "the presenter ducked
it"** — the same fault separation #56 already draws for questions a colleague
waved away.

### 5. The rider — the zero-audio refund

On settlement, whatever the end reason and whatever route led there (relay,
meter cap, reaper): **if the session consumed billed interrogation seconds
and processed zero STT seconds, every tick is refunded**, through
`LedgerService` under its own entry reason (`refund_unheard`) so the ledger
row itself says why the money came back. Zero exactly, deliberately — "very
little STT" is a judgement about a partially working room and a different,
murkier rule; zero is a fact, and the refund it triggers is unarguable. The
mute-mic farm gets a room that asks nothing and is idle-reaped in ninety
seconds; there is no value to extract.

Since the opening statement gives the presenter the floor first, a genuinely
working room cannot reach settlement with zero STT. This check is what turns
CLAUDE.md's "refunded automatically on technical failure" from a sentence
into code.

## The mechanism, mapped onto what exists

The implementation is smaller than the feature sounds, because two pieces of
the machinery were built anticipating it.

**Disconnect closes the interrogation span; resume opens a new one.** This is
the load-bearing move. `SettlementService._interrogation_seconds` already
*sums* spans — its comment names "sessions that were interrupted and resumed"
— and the meter's `_live_rooms` already joins on an **open** interrogation
span. So closing the span on disconnect suspends, in one stroke and with no
new conditions in the money path:

- **billing** — the room drops out of the meter's join, and on resume
  `ticks_due` is derived from the *sum* of span seconds, so the ledger's
  `(session_id, tick_index)` idempotency continues exactly where it left off
  and the tunnel seconds simply never enter the arithmetic;
- **the caps** — session and overdraft caps are checked only on rooms the
  meter sees, and both measure consumed spans, not wall clock;
- **the idle clock** — quiet-time is measured from
  `GREATEST(last_user_speech_at, current_span.started_at)`, so the new span
  re-bases idle on resume without fabricating a speech timestamp;
- **`session_costs`** — the span sum settlement already records is now also
  the billed truth, with no correction column.

**`disconnected_at` drives exactly one thing: the reaper's window.** A new
reaper path settles `active` sessions whose stamp is older than
`RECONNECT_WINDOW` as `client_disconnect` — the same close the relay used to
run immediately. The stamp is cleared on resume. Arrears ticking means no
refund is owed on that ending, same as today.

**A connection nonce guards the stamp.** Each accepted socket writes a fresh
`connection_id` onto the session; the relay's disconnect handling stamps
`disconnected_at` only `WHERE connection_id` is its own. Without this, a
half-open socket's delayed death would stamp a room its owner had already
resumed — stopping its billing and starting its reaper clock while the
presenter is mid-answer. Database-enforced, so it holds across replicas; the
in-process case additionally kicks the stale socket the moment the new one is
seated.

**The orphan backstop stays.** The reaper's existing ACTIVE path
(`last_progress_at` stale past `ORPHAN_TIMEOUT`) still catches the drop the
server never saw — the half-open socket whose relay never ran `_end`. Its
old comment ("there is no reconnect window") is updated: the *cost* rationale
it cited — holding a voice agent open bills for an empty room — died with the
move to `OrchestratedProvider`, where an idle room synthesises nothing and
costs nothing while nobody speaks.

**What deliberately does not change:** `user_ended` and `provider_failure`
still settle immediately through the paths they have; tickets stay
single-use with a 30-second TTL; the one-live-session lock is untouched; the
End tap's server-first ordering (#82) is untouched.

**The recording survives the gap.** The relay that lost its socket saves the
segment it heard, exactly as it always saved a finished room; the relay that
resumes seeds its mixer with that segment, decoded (`from_opus`, the read
half `encoding.py` never needed until now). The mixer's clock is what
transcript offsets are read from, so the seed is what keeps every pre-drop
line anchored to a moment the final file actually contains — and the final
save then overwrites the same key with the whole room, its row upserted
rather than inserted, because two saves per room is now the ordinary shape.
A room with recording off seeds nothing and loses nothing: offsets exist to
anchor playback, and there is no file to play. The audio the tunnel itself
ate is simply absent from the recording, which is the truth of the room.

## The client's half

The app already tells a dropped line apart from a chosen End (shipped
2026-08-22). What it gains: on abnormal close, re-mint and reconnect with
backoff inside the window behind a "Reconnecting…" surface, land back in the
live room on success, and fall through to the debrief only when the window is
spent. The contract change is one new endpoint; the socket protocol is
unchanged.
