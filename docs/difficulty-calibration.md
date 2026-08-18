# Calibrating Difficulty

**Status:** decided 2026-08-18, opening task #55. Taken with the human on the
same day, before any code.

`Product.md` §7 puts this in Phase 3 and `CLAUDE.md` states the requirement in
one line: *"Difficulty calibration escalates across sessions — a first session
that destroys the user produces churn, not resilience."* It sits directly under
Open Risk #1, which is that being attacked at all is the riskiest assumption in
the product.

It was deliberately sequenced after Phase 4. Calibration needs a signal about
how the last room went, and the honest signal is ranked weak answers — which
did not exist until #57.

> **Naming.** The stored fact is the **difficulty level**. The process that
> moves it is **calibration**. What the level actually sets are the **press cap**
> and the **dispute budget**. There is no new domain term here and none is
> wanted; "room temperature" is a different thing entirely and must not be
> confused with this.

---

## Problem

Nothing in the product varies by user. Every room is the same room: rule 2 of
`_SELECTION_INSTRUCTION` allows exactly one press, `dispute.DISPUTES_PER_ROOM`
is 2, and `Archetype` is frozen config identical on every session. A user's
first interrogation and their fortieth are indistinguishable.

**The constraint that shapes every option here is a measurement the codebase
already made twice.** Asked *"did the presenter dodge?"*, a model said yes on
4 of 4 dodges **and** 4 of 4 genuine answers (#43). Asked to weigh three
selection criteria joined by "or", it took the easiest one and gave the CFO
7 of 8 turns (`scripts/rotation.py`). Both were fixed the same way: ranked steps
with a hard prohibition, and a criterion that is checkable rather than a
judgement.

So a difficulty dial phrased as an adjective in a prompt — "go gently", "give
them nothing" — is the exact shape that has already failed here. It would be
unmeasurable, irreproducible between two runs at the same setting, and quite
possibly inert.

---

## Decisions

### 1. The dial is integers code already obeys

Calibration moves two numbers and touches no persona:

- **The press cap** — how many consecutive turns a panelist may spend pressing
  its own unanswered question. Rule 2 of `_SELECTION_INSTRUCTION` hard-codes
  one.
- **The dispute budget** — `dispute.DISPUTES_PER_ROOM`, how many turns in a room
  may open by taking issue with a colleague's priorities.

Both are enforced by code rather than asked for in prose, both have a measured
baseline, and both make a level *reproducible*: level 3 is the same room every
time, which is what lets `scripts/rotation.py` check it at all.

Nothing is added to `_persona_of`. An archetype stays exactly as written —
`persona`, `attack_strategy` and `cadence` are who somebody is, and a person
does not become a different person because you have had four sessions.

### 2. The signal is weak answers the presenter was at fault for

`weakness.Weakness` already anticipates this in writing: *"the prep sheet groups
by this, sparring branches on it, and #55 will count it."*

Only the kinds the presenter owns count. `PrepSheet.tsx` already splits them:

| Counts | Does not count |
| --- | --- |
| `evasive`, `unsupported`, `contradicted`, `unanswered` | `dismissed` — a panelist cut across them |
| | `not_reached` — the room ran out of time |

That split is the whole of #56, and undoing it here would harden the room for
somebody whose questions a *colleague* waved away.

**A model produces this reading, and that is a decision already taken.** #57
reversed a code-first design on exactly this point: code cannot see a fluent,
specific, confidently wrong answer, and that is what §1 means by attacking
substance. Re-deciding it in the opposite direction here would leave two parts
of the same phase disagreeing about what a weak answer is.

**The movement is capped at one step per session, in either direction.** This is
the guard against the feedback loop the model-in-the-loop creates: a reader
having a bad week can cost a user one rung, never four.

*Open, and honestly so:* the thresholds — down at half the questions, up at a
fifth — are **judgements with no data behind them**, in the same position every
price in `Product.md` §4.4 was in before §4.3 was built. They should be revisited
against real rooms, and this doc should be the thing that gets edited.

### 3. One level per account

A `smallint` on `accounts`, beside the tier and the three balances.

Not per panel, and the schema is the reason it was not seriously contested:
`modules/panels/` has **no `models.py`**. A panel is a list of archetype names
handed to `assemble` at session start and written to `SessionPanelist` rows —
there is no durable panel to key anything on, so "per panel" means inventing
persistence.

Keyed on the composition instead — the sorted archetype names — it would work,
and it would be wrong: swapping one panelist resets the room to level 1. That is
an accidental reset for anyone experimenting with the roster and an obvious way
to make the room go easy on purpose.

The deeper reason is what the dial measures. Press cap and dispute budget are
how hard the room *pushes*, not what it pushes on. Resilience under pressure
transfers between a board readout and a demo day even when the subject does not.

`billing/deletion.py` needs no change: `accounts` is already in `DESTROYED`.

### 4. Three rungs, and today's room is the middle one

| Level | Press cap | Dispute budget | |
| --- | --- | --- | --- |
| 1 | 1 | 0 | Followed up on, never cut across |
| 2 | 1 | 2 | **Exactly what ships today** |
| 3 | 2 | 2 | Pressed twice on an answer they dodged |

**The press cap never reaches zero, and that is the load-bearing part.** An
earlier draft of the selection prompt forbade consecutive turns outright, and
its own docstring records why that was wrong: *"It gave up the sharpest move a
room has — the person who asked something noticing it was not answered."* A
level-1 room with no press is not a gentle version of this product; it is a room
that has stopped doing the thing the wedge is made of, shipped to the one
session that has to sell it.

So the floor softens the **disputes** instead. Being cut across by a colleague
is the mildly dismissive turn #54 introduced, and a first-timer being talked
over by two panelists is precisely the line §434 draws: *"Hostility is the
product; humiliation is the churn."*

Three rungs rather than four because **every number above is either today's
measured figure or zero**. A fourth would have to invent one — three disputes
contradicts `dispute.py`'s own reasoning that two is *"a seasoning rather than a
texture"*, and an Auditor budget does not exist to relax. Fake precision on a
dial nobody can perceive is worse than a short ladder.

### 5. Named in the debrief, and the user can dial it

**Visible as words, in the debrief, never as a number and never on the live
screen.** The interrogation screen is hands-free by design (`CLAUDE.md` →
Frontend), so nothing about difficulty may live there regardless. What the
debrief says is what happened:

> "They pressed harder this time than last."

A first session says nothing — there is no last time to compare against.

Credit is why this is said at all. §434 routes the user into rebuilding the
answer, and resilience nobody noticed they built is worth nothing. Words rather
than numerals follows `PrepSheet.tsx`'s `howOften()`, and a level with no number
is much harder to treat as a score — which is the drift toward the
delivery-metrics product the wedge exists to refuse.

**And the user may set it, up or down.** The control lives on panel setup,
beside choosing who is in the room: how hard they push is the same decision,
made at the same moment, and it is the only screen where the choice has visible
consequences seconds later. It writes the same account-level number; nothing
becomes per-room.

Decision 4 is what makes a downward control safe. Because level 1 still presses,
**a user who dials all the way down cannot turn the wedge off** — they get a
room that follows up on a dodge and does not talk over them.

### 6. Calibration resumes from wherever the user leaves it

A level the user set behaves exactly like one they earned: the next bad session
lowers it, the next good one raises it.

Not a floor. Handing somebody the power to lock themselves into the room that
destroyed them puts the one mechanism built to prevent that churn out of reach —
of the user most likely to need it, since asking for the hard room and being
destroyed by it is a specific and predictable sequence.

It is not silent either, which is what makes this acceptable rather than
patronising: decision 5 already has the debrief say *"they went easier on you
than last time."*

### 7. A skipped debrief moves nothing

No debrief, no weak answers, no signal, no change.

`DebriefService.weak_answers()` computes lazily on debrief open and refuses
outright on `RoomBroke` and `RoomHasNoQuestions`. All three cases land in the
same place: a room with no reading is a room the level does not move on.

Moving the read to the settle path would close the gap and was rejected. It
reverses #57's laziness and spends a reasoning model on every room including
abandoned ones, and §4.3 already names the unmetered phases as the model's
largest uncontrolled exposure with #14 not yet run.

The gaming surface is real and self-defeating: avoiding escalation costs the
user the unmetered coaching they already paid for. It also fails in the right
direction — somebody who skips the debrief is skipping the phase that rebuilds
the answer, and hardening the room for exactly that person is the churn Open
Risk #1 describes.

---

## What must be true when it is built

- **The prompt and the roster still agree.** `_silence_of` stamps the phrases
  `_SELECTION_INSTRUCTION` quotes, and
  `test_the_rules_and_the_roster_use_the_same_words_for_silence` fails loudly
  when they drift. A press cap of 2 needs a marking for a third consecutive
  turn, on both sides at once.
- **The measured behaviour is re-measured.** `scripts/rotation.py` is how the
  cap was chosen; every rung has to be run through it, because a templated
  number in prose that was tuned as fixed prose is not the same prompt.
- **Level 2 is byte-identical to today.** The middle rung must produce the room
  currently shipping, or every figure in `rotation.py`'s history describes
  something that no longer exists.
- **The level is clamped on read, not only on write.** A row holding 7 must
  produce a real room rather than an exception on the live path.
- **A first session is level 1**, from the column default, with no lookup and no
  special case.
- **Nothing about this reaches the live interrogation screen.**
