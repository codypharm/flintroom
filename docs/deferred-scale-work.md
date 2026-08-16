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
| A broker for extraction work (Celery/SQS/pgmq) | Extraction workers need scaling that a separate deployment of the sweep loop cannot satisfy, or queue claim latency shows up in a profile | The bottleneck is the vendor's tokens-per-minute, not the queue — see the arithmetic below. Extraction is also not idempotent (a duplicate run is a second invoice and a second set of claims), so at-least-once delivery means the `extracting`/`claimed_at` claim stays either way: a broker is added *to* the state machine, not instead of it, and two systems then hold opinions about what work exists. |
| Throttle on the provider's rate-limit response headers | Sustained 429s at a concurrency nobody wants to keep tuning by hand | `extraction_concurrent_calls` is a knob that can be turned in config today, and with zero users there is no number to size a limiter against. Deriving concurrency from a declared allowance was refused outright: the arithmetic needs seconds-per-call, which nothing can currently measure, so it would launder a guess into a formula that reads as computed. Headers are the honest version and need traffic to be worth it. |

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

### Rough arithmetic behind deferring an extraction broker

At a 20-page deck per call and ~55k input tokens per call, with a 3× evening
peak over the daily average:

| Decks/day | Calls/min (peak) | Tokens/min (peak) | DB claims/sec |
| --- | --- | --- | --- |
| 1,000 | 2 | 115k | 0.03 |
| 10,000 | 21 | **1.1M** | 0.35 |
| 100,000 | 208 | **11.5M** | 3.5 |
| 1,000,000 | 2,083 | **115M** | 35 |

The two columns never bind together. **Token throughput saturates a typical
organisation allowance at roughly 10,000 decks a day, where the database is
doing 0.35 claims a second** — three orders of magnitude below anything
`SKIP LOCKED` notices. A broker would be optimising the least loaded component
in the system at every volume this product plausibly reaches.

What does scale, in order: a limiter that understands tokens rather than tasks
(no broker provides one), tokens per page (2,750 is a choice, not a constant),
the Batch API's separate high-throughput lane, and running the sweep as its own
deployment — which needs no broker either.

The 55k and the 3× peak are estimates, not measurements. The conclusion survives
being wrong by 2× in either direction; the crossover point does not.

---

## Object storage: which S3, and why it is not decided yet

**Deferred 2026-08-16, when `core/storage_s3.py` landed. Trigger to decide: task
#29 resolving that sessions retain audio.**

Development runs MinIO. Production is undecided, and deliberately so: the code
speaks the S3 API and holds no vendor SDK above `core/storage_s3.py`, so AWS S3,
Cloudflare R2, Backblaze B2 and a self-hosted MinIO differ by four environment
variables and `S3_ADDRESSING_STYLE`. Choosing now would be choosing without the
one input that matters.

### On today's access pattern the choice is worth nothing

`docs/ingestion.md` deletes the source document once extraction succeeds, so what
is stored long-term is thumbnails at roughly 20KB:

```
storage   50,000 thumbnails × 20KB       ≈ 1 GB     ≈ $0.02/mo, either vendor
          source decks live for minutes  ≈ nothing
egress    500,000 views × 20KB           ≈ 10 GB    ≈ $0.90 S3 / $0 R2
```

Single-digit dollars a month at ten thousand users. The retention decision that
made the privacy story simple also made the bill too small to pick a vendor on.

### Retained session audio is what changes the answer

Task #29 records the intent that sessions are saved so users can play them back.
That inverts the profile completely — megabytes per session, served repeatedly to
phones, and retained rather than deleted.

The relay carries PCM16 at 16 kHz mono, which is 1.92 MB per minute. A
twenty-minute interrogation is therefore:

```
raw PCM16              ≈ 38 MB per session
Opus ~24 kbps mono     ≈ 3.6 MB per session      — about a tenth
```

At 10,000 users keeping four sessions a month, twelve months in:

| | stored | storage/mo | egress/mo | total |
| --- | --- | --- | --- | --- |
| Opus on R2 | 1.7 TB | ~$26 | $0 | **~$26** |
| Opus on S3 | 1.7 TB | ~$40 | ~$19 | **~$59** |
| Raw PCM on S3 | 18 TB | ~$420 | ~$190 | **~$610** |

**The encoding decision is worth about 10×; the vendor decision is worth about
2×.** Both are real and they are not the same size, so decide them in that order.
Rates are approximate and move; the ratios are the durable part.

### Why this cost behaves unlike every other one in the product

Every other cost here is per-use — a minute of interrogation, a page extracted.
Retained audio is the first cost that **compounds**: it accrues monthly, grows
monotonically with every session ever run, and keeps being charged for a user who
churned a year ago. Nothing else in the product does that.

It is also unmetered by construction. The metering boundary is locked to live
interrogation (`Product.md` §4.1), so retained storage is revenue-free ongoing
cost — structurally the same problem as extraction in `docs/ingestion.md`, but
recurring rather than one-off.

Three controls, in the order they should be considered:

1. **Encode, don't store raw.** Not a policy question. Worth ~10× on its own.
2. **A retention window per tier** — the cheapest structural answer, and the same
   shape as the per-tier page budget already decided. `Product.md` §4.4 already
   sells "full session history" as a Pro differentiator, so tiered retention is
   consistent with what is sold rather than a new promise. A window also has to
   be written down for the privacy policy regardless (Open Risk #5), so this
   control costs a decision that is owed anyway.
3. **Billing on retained storage** — raised by the human 2026-08-16 as a
   possibility, explicitly not a decision. It would add a second metered axis
   beside Time Under Fire, which is a pricing change and therefore human's call,
   blocked behind the §4.3 cost-instrumentation task like every other price here.

### One caveat before committing to R2

R2 is S3-compatible across the common surface, and our four operations sit
firmly inside it. Lifecycle rules, server-side encryption with customer-managed
keys, and multipart edge cases are where compatibility thins out — check them
against R2's own list rather than assuming, particularly since a tiered retention
window is most naturally implemented as a lifecycle rule.

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
