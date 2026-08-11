# Deferred Scale Work

**Status:** deliberately not built. Recorded 2026-08-11, after fixing lost updates on the ledger (`1a5d848`).

Each item below was considered and declined *for now*, with the signal that should
reopen it. A deferred list without triggers is a list nobody revisits — the trigger
is the point of this document, not the item.

**Context that governs all of it:** `Product.md` §9 records zero users, zero
latency measurements and zero observed cost data. Open Risk #1 — whether people
tolerate being attacked — is unvalidated. Open Risk #6 warns against building
speculatively. Everything here adds a failure mode to code that moves money, so
the bar for building it early is high.

---

## The property that keeps this cheap to defer

Ledger contention is **per account row**, and `Product.md` allows one active
session per user, so a user only ever contends with themselves. Nothing
serializes one user against another.

That means the write path shards perfectly by `user_id`, and every item below
stays a deployment change rather than a rewrite. **Protect this property in
every future decision.** The things that would break it: a global counter, a
cross-user aggregate on the write path, a shared lock, or any table where one
row is touched by many users' sessions.

---

## Do first — not deferred, just not done yet

| Work | Why it is first |
| --- | --- |
| Connection pooling via Supavisor / pgbouncer in **transaction** mode | This is what actually breaks first. FastAPI across several workers exhausts Postgres connections long before write throughput matters. Not a scale optimization — a correctness-under-deployment requirement. |

Note for whoever wires it: transaction-mode pooling does not support session-level
state. `SELECT ... FOR UPDATE` is fine — it is transaction-scoped — but prepared
statement caching needs care with asyncpg.

---

## Deferred

| Work | Trigger to build it | Why not now |
| --- | --- | --- |
| Shard / partition `ledger_entries` by `user_id` | Ledger write latency p99 degrades, or the table passes a few hundred million rows | Writes shard cleanly by construction (above). Until a single primary is measurably struggling, this is complexity with no observed problem behind it. |
| Read replicas for balance reads | Read load measurably competes with the tick write path | Balance reads are O(1) single-row lookups on the primary key. Replicas add replication lag to a number that is money — a user could see a stale balance after a top-up. |
| Cache balances in Redis | Primary cannot serve balance reads at the session-start rate | Introduces a second source of truth for money. The cached balance in `accounts` is already the cache over `ledger_entries`; a third layer needs a real measured reason. |
| Batch or queue ticks through a broker | Ledger writes approach the primary's sustained write ceiling | Ticking in arrears depends on the charge being durable when it returns. A queue puts money in flight and turns every retry into a distributed-systems question. |

### Rough arithmetic behind the deferral

At one million *concurrent interrogations* — not registered users, which is a
completely different number — the tick loop is roughly `1,000,000 / 15s ≈ 67,000`
ledger writes per second. That does exceed a single Postgres primary.

But the same scenario costs about **$120,000 per wall-clock minute** in voice at
the §4.4 assumed $0.12/min. The binding constraint is the voice provider's
concurrency ceiling and its invoice, not the database. Sharding at that point is
a funded problem, not a design problem.

Both figures inherit §4.3's unverified vendor list-rate assumptions (Open Risk
#4), so treat them as order-of-magnitude only.

---

## Open question for the vendor, not the codebase

**What concurrent-session ceiling does the ElevenLabs contract actually carry, and
what does it cost at that concurrency?** This bounds real capacity long before
anything in this document does. `CLAUDE.md` already requires verifying cost per
minute at real concurrency against actual invoices; this is the same question
asked early enough to matter.

---

## Not on this list, because they are already required

Rate limiting on auth and session-start, idempotency, audit logging, and per-account
spend ceilings are mandated by `CLAUDE.md` and the Metering Rules. They are not
scale optimizations to defer.
