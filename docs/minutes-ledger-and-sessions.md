# Minutes Ledger and Session Lifecycle

**Status:** decided, not implemented. Resolved via `grill-me` on 2026-08-11. Tests are written against this document; implementation follows the tests.

**Scope:** the minutes ledger (Weeks 1–2, `Product.md` §7) and the session state machine it depends on. Governed by the Metering Rules in `CLAUDE.md` and §4 of `Product.md` — where this document and those disagree, they win and this is the bug.

This records **why** each choice was made. The tests will prove the behavior; only this explains the reasoning, and the reasoning is what stops a later pass from "simplifying" a deliberate decision back out.

---

## Part 1 — The ledger

### Resolved

| Decision | Choice | Why |
| --- | --- | --- |
| Storage model | Append-only signed entries + cached balance, written in one transaction | The entry log *is* the audit trail `CLAUDE.md` already requires, so there is no second system to drift out of agreement with the first. Balance reads stay O(1) on the session-start hot path. A mismatch between replayed entries and the cached balance is a detectable bug rather than a silent one. |
| Decrement cadence | Tick **in arrears**, ~15s, idempotent on `(session_id, tick_index)` | Charging after the interval elapses means a crash, force-quit, or dropped network can never overcharge — the ledger reflects exactly the time served. Idempotency key makes retries safe. Worst-case unbilled time is one interval. |
| Units | Integer seconds | Float money is a bug waiting to happen; the 15s tick makes seconds the natural grain. |
| Rounding | Charge exact seconds; UI floors to whole minutes | 605s reads "10 minutes left" — the user always has slightly more than promised, never less. Generosity without a lie, and it satisfies §4.6 without a depleting counter. |
| Buckets | Three typed: `allowance` → `free` → `topup` | Spend what expires soonest, then what cost the user nothing, then what they paid for. §4.5 fixes allowance-before-topup so nobody burns purchased minutes while free ones remain. |
| Reset | Lazy on read, keyed by `period_id`; RevenueCat webhook accelerates | No scheduler dependency (the stack has none) and no silent failure mode. A dropped webhook costs nothing because the next read repairs it. Aligned to the RevenueCat entitlement period, not the calendar — anything else drifts from what the user paid for. |
| Zero mid-session | Bounded grace (~120s), **forgiven** | §4.5 forbids interrupting a live session. At the cap a spoken handover is owed; as of 2026-08-22 the *session* cap has one (`agents/closing.py` — the room calls time in a panelist's voice, after whoever is speaking) and the grace cap does not yet. Writing off two minutes costs ~$0.32 at the §4.4 all-in rate; chasing it into next month is the engaged-user farming §4.5 warns against. |
| Refunds | Server-side finalizer only, typed reasons, new positive entries, idempotent on `(session_id, reason)` | A client can never request a refund. Refunds are entries, never mutations, so history stays replayable. |
| Refund policy | Unserved and degraded time only | Idle refunds from last detected speech to cutoff; provider failure refunds from the failure timestamp onward; completed or user-ended refunds nothing. Arrears ticking already means unserved time was never charged. |
| Entitlement source | Local cache, webhook-refreshed, re-verify before denying | No network call on the latency-sensitive path, and RevenueCat's uptime is not a prerequisite for starting a rehearsal. Same lazy-repair pattern as the reset — one idea to understand, not two. |
| Data access | FastAPI only; RLS deny-all as defense-in-depth | The app holds no Supabase credentials, so the ledger is unreachable from a client even if a key leaks. RLS is the second wall, not the only one. Keeps a future web client free per `CLAUDE.md`. |
| Circuit breaker | Alert only — never refuses a user | One-active-session (below) already bounds runaway cost, and idle detection kills abandoned sessions. A hard daily cap would convert the monthly allowance into a daily one, contradicting the locked bursty-usage decision and failing the user on their highest-stakes day. A breach is a bug report about our own system, not a verdict about the user. |

### Notes that do not fit the table

**Grace measures the current overdraft, not a per-session ration.** `grace_started_at` is cleared the moment a tick draws without overdrafting, so a user who tops up mid-interrogation and later runs dry again gets a full window rather than the remainder of an old one. The alternative — one window per session — cuts a user off seconds after they gave us money, which is the worst moment in the product to do it. Worst case is another two minutes written off, against a user who has just demonstrated they will pay.

**Entering grace and leaving it are one decision, asked once per tick.** `enter_grace()` stamps the clock on the first overdrawn tick and answers whether the cap has passed; `leave_grace()` is called on the other branch of the same `if`. Split into a stamp and a separate check, a caller that stamps and forgets to ask is a room running past the cap on our invoice, and one that asks without stamping never reaches the cap at all. The cap is compared against Postgres' clock, for the reason given under Authority and detection.

**Grace forgiveness must be an entry.** The write-off appears in the log as a typed `grace_forgiven` entry. Omitting it instead would break reconciliation between the entry history and the cached balance — which was the entire reason for choosing an append-only model.

**`session_costs` is separate from the ledger.** Cost telemetry and billing must be able to disagree; that disagreement *is* the §4.3 reconciliation. Never derive one from the other.

**Webhook handling** is already fixed by `CLAUDE.md`: signature verified before the payload is parsed, unverified rejected and audit-logged, grants idempotent on the provider event id.

---

## Part 2 — Session lifecycle

### States

```
provisioning ──► active ──► finalizing ──► settled
     │                                        │
     └──► failed                              └──► coaching spans appended later
```

| Transition | Trigger |
| --- | --- |
| `provisioning → active` | Voice channel established; first interrogation span opens |
| `provisioning → failed` | Spin-up failed or timed out — nothing billed, lock released |
| `active → finalizing` | End intent, 12-min cap, grace cap, idle timeout, provider failure, or 3 missed ticks |
| `finalizing → finalizing` | Idempotent resume after a crash mid-settle |
| `finalizing → settled` | Last tick, refunds, and grace forgiveness all written |
| `settled` + coaching span | Unmetered, no ledger writes, permitted later |

**Lock holders:** `provisioning`, `active`, `finalizing`. Released at `settled`, so a user in yesterday's debrief is not blocked from starting a fresh interrogation.

### Why these states

- **`provisioning` is distinct** because ElevenLabs agent spin-up takes real time and can fail before any audio exists. It holds the one-active-session lock but bills nothing, so the reaper can kill a stuck one in seconds rather than minutes. Without it, a spin-up failure is indistinguishable from a real session in every query and cost report.
- **`finalizing` is distinct** because settlement must be crash-safe. Without it, nothing separates "finished settling" from "died halfway," and the reaper cannot safely retry.
- **Grace is a `grace_started_at` timestamp on `active`, not a state.** Nothing about ticking or idle detection changes during grace, so a separate state would double the transition table for no behavioral difference.
- **`settled` means billing closed, not session closed.** §3.5 calls debrief and sparring "the part users will pay for," and they are unmetered — refusing them because real life interrupted costs us nothing to grant and costs the user the thing that sells the subscription.

### Session scope

One session row spans the whole arc, with an append-only child table of **phase spans** (`phase`, `started_at`, `ended_at`). The ledger references interrogation spans only, giving metering a structural anchor rather than a conditional check on every write path.

This matches §4.3, which specifies one `session_costs` row per session carrying `interrogation_seconds`, `debrief_seconds` **and** `sparring_seconds`. It also yields exact per-phase durations, which §4.3 needs in order to measure the median coaching duration it admits is currently a guess.

### Authority and detection

- **Server-authoritative.** The End button sends an *intent*; the server decides. Nothing money-relevant comes from the client.
- **The 15s billing tick doubles as the heartbeat.** One mechanism, not two.
- **The meter is a sweep, not a timer per room.** A per-session task lives in one process, so a crash, a restart or an ordinary deploy would stop billing every open room while the voice provider carried on invoicing us — and the reaper would not catch it, because those sessions still look alive. `tick_index` is derived from how long the interrogation span has been open rather than counted, which is what makes the sweep stateless: two workers compute the same index, a sweep that missed a beat catches up, and one that runs twice is refused as a duplicate. It resumes from the highest index the ledger already holds, which is a read of the entries rather than a cursor to go stale.
- **The sweeps run as a loop in every API process**, started and stopped by the application lifespan — not a task queue. A queue's guarantee is that exactly one worker takes each job; both sweeps are idempotent, so overlapping processes reach the same answer and the duplicate writes are refused. Paying for a broker to prevent a harmless overlap buys nothing. The cost of this choice is that if every API process is down, nothing bills while the provider keeps charging for open rooms — arrears means the loss is ours, never the user's. That is why every pass logs even when empty: **an alert on the absence of `meter_swept` is what makes this design safe**, and there is no substitute for it.
- **Shutdown asks, it does not cancel.** The sweeps write money, and a task cancelled inside a commit is the one shutdown that could leave a session half-settled — the exact state the reaper exists to repair, so causing it on every deploy would be self-inflicted.
- **Caps are enforced per sweep, not per tick.** The session cap and the grace cap are about elapsed time. Checked only when a tick happened to be due, a room could sit past its cap until the next interval elapsed.
- **Charging past the cap is deliberate.** A late sweep bills every interval that actually ran, including any beyond the twelve-minute cap. The room was open and the provider charged us for it; overshoot is bounded by the sweep's own interval, which is the argument for keeping that interval short.
- **Metering refuses a room that is no longer live** (`SessionNotLive`, 422). The sweep selects live rooms and then bills them, and a user pressing End lands in that gap constantly. Both grace branches refuse, so whether a lost race is survivable does not depend on the user's balance at that moment.
- **Disconnect:** 3 missed ticks (~45s) → reaper finalizes as `client_disconnect`. Arrears ticking means no refund is owed; the ledger is already correct. The lock releases so the user can immediately start fresh. No reconnect window — holding an agent open costs money to talk to nobody.
- **Idle:** no *user* speech while the panel awaits an answer. Panel speech does not count as activity, because a stuck agent monologuing to an empty room is precisely the expensive failure. Spoken check-in at ~60s, finalize at ~90s, refunding the whole idle window.
- **A room nobody has ever spoken in is idle from the moment it opened.** That is the abandoned room the check exists for, and it is the expensive one. It is also safe against the obvious objection, because the user speaks first: `Product.md` §3.2 is "speak, and the panel goes to work", and §3.3 requires every challenge to be grounded in something the user said or attached, so the panel has nothing to open with. The first word lands within seconds of a real session and every answer resets the clock after that. What remains is the user who opens a room and then freezes — 90 seconds to say anything at all. Narrow, and 90 seconds of dead air at the start of a rehearsal you chose to begin is itself a reasonable signal. If it ever bites, start the clock at the first word and give "never started" its own longer fuse.
- **Idle outranks the session cap.** Both can apply to the same room — a session abandoned at 90s and still open at twelve minutes, because the sweep was down in between. The order is not bookkeeping: only idle refunds, so recording that room as `session_cap` says the user consumed their whole session and hands them nothing back.
- **The idle refund returns whole ticks, rounded the user's way.** Every tick from the one straddling their last word onward, to the buckets it came from. At most 15s more than strictly owed, which matches the ledger's rounding elsewhere and avoids prorating one tick back across buckets on the only path that pays money out. `record_speech` is the seam the voice layer writes to; it is not audited, because a room with somebody talking in it is the ordinary state of the product.
- **What the reaper reads is one `last_progress_at` column**, touched by every transition and by every tick, and compared against Postgres' clock rather than the process's. One column rather than a timestamp per state: "when did this session last do anything" gets one answer, and a transition cannot be added that silently leaves a session looking stuck. Not `started_at` — a twelve-minute interrogation that has just begun settling is old but not stuck, and reaping on age would race the settlement already running. Not the app clock — the reaper runs on more than one worker, and a skewed one would throw users out of rehearsals they are still in.
- **A sweep survives its own contention.** The reaper selects, then acts, and a user can end their own session in between. Losing that race rolls back and moves to the next session; it never ends the batch, because the sessions left behind are still stuck and the next sweep would meet the same contention with more to do. The rollback is also what discards the staged `session_reaped` audit row, so a reaping that did not happen leaves no row claiming it did. Anything that is not a typed application error is a bug and is left to propagate.
- **Enforcement:** transition logic in the service layer with a transition table; Postgres enforces the partial unique index for one-active-session, the enum CHECK, and `NOT NULL settled_at` when settled.

---

## Part 3 — Edge cases that need tests before code

1. **Multiple elapsed periods.** A user who does not open the app for three months has three missed period boundaries. The reset must grant **once**, not three times — the check must walk to the *current* period, not the next one.
2. **Negative balances are reachable.** Grace-forgiven means the cached balance can go negative. Every read path and display must handle it; a user must never see "−2 minutes."
3. **Sub-minute balances.** Floored display means 59 seconds reads as "0 minutes" while the session is still startable. Copy must not lie: "less than a minute left."
4. **Grace forgiveness reconciles.** Replaying entries must equal the cached balance after a forgiven overdraft.
5. **Tick idempotency.** Replaying `(session_id, tick_index)` must not double-charge.
6. **Reaper, three cases.** Stuck `provisioning`, orphaned `active`, and stuck `finalizing` — the third is the one no user action will ever resolve.
7. **Concurrent start.** Two devices racing must produce one session and one 409, not two sessions.

---

## Part 4 — Open

- **Recording retention window.** Open in `Product.md` §9. Bounds how long a settled session stays reopenable for coaching. Blocks the debrief module and the App Store submission; does not block the ledger.
- **Coaching soft cap, per-span vs cumulative.** Largely moot now that the coach is scoped by subject rather than by clock (see `Product.md` §9 → Capabilities and Constraints). §4.7's ~20 minute cap remains as friction against an idle open session; per-span is sufficient.
- **Period length is a 30-day placeholder.** The reset decision says the boundary follows the RevenueCat entitlement period, not the calendar — someone who subscribes on the 3rd renews on the 3rd. Until the RevenueCat webhook lands there is nothing to read that from, so `PERIOD_LENGTH` in `billing/service.py` advances by a flat 30 days. It is marked in code. Replace it when the webhook arrives; a user on a 30-day cadence drifts a day earlier each month against a calendar-month subscription.
- **Every cost figure quoted above** derives from §4.3's unverified vendor list-rate assumptions. The grace write-off arithmetic and the circuit-breaker threshold both need re-deriving once real telemetry lands.

---

## Appendix — Schema sketch

Derived from the decisions above, not separately decided. Table and column names are proposed; the shape is not.

```
accounts
  user_id, entitlement_tier, period_id, period_ends_at,
  balance_allowance_seconds, balance_free_seconds, balance_topup_seconds

ledger_entries                      -- append-only, never updated or deleted
  id, user_id, session_id?, bucket, delta_seconds, reason, period_id?,
  idempotency_key UNIQUE, created_at
  -- reason: grant_allowance | grant_free | grant_topup | expire_allowance
  --         | tick | refund_idle | refund_provider_failure | grace_forgiven

sessions
  id, user_id, state, panel_config, grace_started_at?, end_reason?,
  started_at, last_progress_at, settled_at?
  -- partial unique index on (user_id) where state in
  --   ('provisioning','active','finalizing')

session_phase_spans                 -- append-only
  id, session_id, phase, started_at, ended_at?
  -- phase: interrogation | debrief | sparring

session_costs                       -- §4.3; telemetry, never billing
  session_id, ... (exact schema in Product.md §4.3)
```
