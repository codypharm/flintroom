# What a room actually costs

Every price in `Product.md` §4.4–4.5 rests on an assumed **$0.12 per
interrogation minute**, and Open Risk #4 says the tier margins collapse if it is
wrong. This is the first measurement against it. It is not the §4.3
reconciliation — that needs a provider invoice — but it replaces the assumption
with observed usage, which is the half nobody had.

## Measured, 2026-08-17

17 real rooms, 13.8 interrogation minutes, from `session_costs`.

| Per interrogation minute | Measured |
| --- | --- |
| Audio transcribed | 50s — a room-minute is not a minute of speech |
| Panel speech synthesised | **371 characters** |
| Panel model tokens | 2,495 in / 80 out |

Two conversions, both taken from the vendor rather than assumed:

- **Scribe: $0.39/hr.** Verified rate, `transcribers/elevenlabs.py`.
- **Flash v2.5: 0.5 credits per character.** Read off a quota error, which
  helpfully stated the arithmetic: 8 credits required for a 15-character line.

Which gives the number that converts any plan into capacity:

> **~186 credits per interrogation minute.**

The Free plan's 10,000 credits/month is therefore about **54 minutes of
interrogation**, and STT draws on the same pool, so the real figure is lower.

## Where the money goes

| | $/min | Share |
| --- | --- | --- |
| Scribe (speech to text) | $0.0054 | ~12% |
| **Panel speech (text to speech)** | **~$0.04** | **~88%** |
| Gemini (the entire panel — routing and composition) | $0.0003 | 0.6% |

**The panel model is a rounding error and transcription is nearly one.** Almost
the whole voice bill is synthesising what the panel says. Any future cost work
that is not about characters synthesised is optimising the 12%.

It also means cost tracks how much the panel *talks*, not how long the room
lasts — two rooms of identical length can differ materially, and a room where
the user does more of the talking is cheaper. That is the right incentive and it
happens to be free.

**The dollar figures move with the plan and the measured usage does not.** Only
the credits-per-minute is a property of the product; the rate is a property of
the contract, and it swings several-fold across tiers. Re-derive rather than
quote these.

## Line length is not a cost lever — decided, 2026-08-17

The obvious saving is a tighter word cap. 371 chars/min is 88% of the bill, so
25 words → 20 would take roughly a fifth off the dominant line, free, with no
vendor change.

**Rejected, deliberately.** The human's call: *"I want the interrogator to talk
well, 20 is small."* The panel's job is to be credible under pressure, and a
challenge clipped to fit a budget is a worse challenge. §3.3's failure mode is a
room that feels synthetic within two minutes, and shaving words to save
fractions of a cent is a direct route to it.

The 25-word cap in `_persona_of` stays where it is, and it is there for
*credibility* — 25 words is already eight seconds of somebody sitting waiting —
not for money. Do not re-open it as a cost measure. If cost genuinely has to
come down, change the plan or the synthesis vendor; the seam in
`voice/speakers/` exists for exactly that.

## Eleven v3 — measured 2026-08-19

The architect moved to a paid plan and asked for expressive panel speech (#34).
Both halves were measured against the live account rather than read from
documentation, because the documentation is ambiguous on the first one and
silent on the second.

**v3 performs audio tags; Flash reads them aloud.** Settled by synthesising the
same tagged line on each model and feeding the audio back through Scribe, which
is a check rather than an impression — a spoken tag lands in the transcript:

| Model | Heard back |
| --- | --- |
| `eleven_v3` | "Scale is irrelevant if the unit economics stay negative. What does each customer cost?" |
| `eleven_flash_v2_5` | "**Skeptical.** Scale is irrelevant if the unit economics stay negative. **Pause.** What does each customer cost?" |

So `TAG_PERFORMING_MODELS` was right about both, and `eleven_v3_conversational`
— which the vendor's model page names as the tag-supporting model — is **not
required**. It is also not available: the account returns
`model_access_denied` for it, which is an account-level refusal rather than a
key-scope one (the same key gets `missing_permissions` for `/v1/models`).

**Two prices, and neither is small.**

| | Flash v2.5 | Eleven v3 |
| --- | --- | --- |
| First byte | 0.887s | **1.280s** |
| Whole take, 6.4s of audio | 1.449s | 3.200s |
| `character-cost`, same 19-character line | 5 | **10** |

The `character-cost` response header is a better source than the quota error
above, and it says v3 is **exactly twice** Flash per character.

That lands on the 88% line. Panel speech is ~$0.04 of a ~$0.046/min room, so
doubling it takes the room to **~$0.086/min** — still inside the $0.12/min
every §4.4 margin assumes, but consuming 72% of it where today's room consumes
38%. In credits: **~372 per interrogation minute**, halving any plan's capacity.
The Free plan's 54 minutes becomes about 27.

The latency is the sharper cost. `docs/panel-orchestration.md` measures the turn
at 1.38s from the final transcript, and `SILENCE_THRESHOLD_SECS` adds 0.7s
before that, so a listener already waits ~2.1s against the ~1.5s at which
`CLAUDE.md` says the illusion breaks. v3 makes that ~2.5s.

**Not adopted wholesale, for that reason.** The room has three places speech is
synthesised and only one of them is racing a listener:

| Where | Waiting for a reply? | Model |
| --- | --- | --- |
| Interrogation turns | Yes — this is the budget | Flash |
| The opening line (#79) | No — nobody has spoken yet | v3 is free here |
| Debrief coach | No — turn-based and unmetered | v3 costs only money |

**Adopted in that shape by the architect, 2026-08-19.** `speech_model` stays
Flash and `expressive_speech_model` is v3; `build_speaker` and
`build_expressive_speaker` are two instances of one adapter sharing one HTTP
client, chosen at construction rather than per call so that nothing can put the
slow model on the latency budget by accident. Setting both settings to the same
value turns the split off.

What that costs in practice is small: one opener of a dozen words per room, plus
the debrief, against 371 characters of panel speech per interrogation *minute*.
The 2x lands almost entirely on lines that are not billed by the minute at all.

Not taken, and worth saying so: the opener copy carries **no** audio tags. The
lines are hand-written and were approved without them, and `test_openers.py`
still forbids a bracket — because an opener falls back to Flash when no
expressive speaker is configured, and Flash would read the bracket aloud. The
coach's prompt is likewise unchanged; it gets the better model's delivery
without being told it may perform. Both are follow-ons, and both are tone
decisions rather than plumbing.

## A room killed under one tick — computed 2026-08-20

`#73` was raised on the premise that a room ending before the meter's first
tick is free to the user and expensive to us. `meter.py` floors elapsed time
into ticks, so a room under `TICK_INTERVAL` (15s) charges nothing, and a room
abandoned to the idle reap is refunded from tick zero — `settlement.py`'s
`_first_unserved_tick` returns 0 when the presenter never spoke, because "no
part of this room was received."

**Corrected 2026-08-21, and #79 is why.** This section originally read that an
abandoned room "synthesises nothing at all", on the grounds that the presenter
holds the floor and no panelist speaks until they have spoken and paused. That
was true of *composed* turns and remains so — nothing is routed, and no model
composes a line. It was never true of the opener. `_open_the_room` runs before
anything is transcribed, so the cheapest possible room still synthesises one
hand-written line.

This is the reopen condition the section named for itself: *"if anything is ever
added that synthesises speech before the presenter has spoken."* It fired the
day #79 shipped and went unnoticed for two days, which is the argument for
writing reopen conditions down.

| | Scribe | Panel speech | Total |
| --- | --- | --- | --- |
| Ended by hand under one tick (15s) | $0.0016 | one opener, ~35 chars | **~$0.009** |
| Abandoned to the 90s idle reap | $0.0098 | opener + one nudge | **~$0.020** |

Openers use the expressive model, which the header measurement above puts at
exactly twice Flash per character — so the cheapest room in the product is
roughly **five times** what this section used to record, and an abandoned one
is nearly double. Still cents, and still the right shape: it is now the panel
*speaking* that dominates even the rooms nobody speaks in, which is the same
sentence as the 88% line and not a coincidence.

The nudge fires once at `NUDGE_AFTER_SECS = 60` against a reap at
`IDLE_LIMIT = 90`.

**The abuse ceiling is set by the one-active-session rule, not by the meter.**
A user holds one room at a time — `ActiveSessionExists`, 409, audited — so the
loop is start, end, start rather than ten in parallel. At the
`SESSION_START_LIMIT` of 10/minute that is on the order of a dollar an hour per
account, against a daily spend ceiling that exists to catch exactly that. And
it buys the abuser nothing: the panel asks nothing, so there are no free
questions to farm — the opener is a fixed hand-written line and tells them
nothing they did not already know.

**The ceiling exists as of 2026-08-21.** It was named in `CLAUDE.md`'s Metering
Rules and leaned on by the paragraph above for two days before anything
implemented it. `SessionService._within_daily_ceiling` sums
`session_costs.computed_cost_usd` over a rolling 24 hours for the one account
and refuses a start past `DAILY_SPEND_CEILING_USD[tier]`, audited as
`daily_ceiling_reached`. Rolling rather than a calendar day: no timezone to
decide, and no midnight at which somebody hammering the API all evening is
handed a fresh budget. Per tier, because a free account holds fifteen minutes
for life — about $0.68 of interrogation — and can never legitimately approach a
Pro account's day.

It reads a column that was null on every row until the same day:
`voice/rates.py` now prices each turn as it is recorded, which is also what
gives §4.3 something that can contradict $0.12/min.

**Decided: no minimum charge.** It would be a metering-boundary change, which
`CLAUDE.md` reserves to the architect, and it would trade a deliberate
user-favouring rounding rule — stated in `settlement.py` as rounding "in the
user's favour by at most one interval, matching how the ledger rounds
everywhere else" — for about one cent.

**Reopen if** the observed median of `session_costs` rows with
`interrogation_seconds < 15` stops being a rounding error against the rooms
that ran, or if anything is ever added that synthesises speech before the
presenter has spoken. The rows are already there: `_record_cost` writes one on
every settle regardless of ticks, so this is answerable from data the moment
there is traffic worth querying.

These figures are arithmetic over the published rates, not observations. §4.3
still wants them reconciled against an invoice.

## Still open

- **No invoice has been compared to anything.** §4.3's acceptance criterion is
  observed cost within 10% of the provider's own figure, and
  `provider_reported_cost` is still null on every row. That needs a billing
  period with real usage in it — task #14.
- **`agent_session_count` is answered but not by an invoice.** Owning the loop
  means one synthesis request per line rather than a per-agent runtime, so the
  assumption §4.3 feared — being billed per concurrent agent — no longer applies
  by construction. Worth confirming against a bill anyway.
- **Debrief and sparring are unmeasured.** They are unmetered, not free, and
  `debrief_seconds` / `sparring_seconds` are still zero because neither phase
  exists yet. §4.3 names the unmetered phases as the model's largest
  uncontrolled exposure.
