# The Debrief and Sparring

**Status:** decided 2026-08-17, opening Phase 4 (`Product.md` §7, week 7).
Resolves the seven questions that had to be settled before any of §3.5 could be
written, taken with the human on 2026-08-17.

`Product.md` §3.5 asks for four things — a voice coach walkthrough, a ranked
weak-answer list, a sparring re-try loop, and an exportable prep sheet — and
opens with the sentence that sets the stakes: *"This is the part users will pay
for. The interrogation creates the problem; this solves it."*

> **Naming.** A *room* is one interrogation. The *debrief* is the unmetered coach
> walkthrough that follows it; *sparring* is the unmetered re-try loop inside it.
> *Auditor* is the domain agent, never the `audit_log` module. The coach is not a
> panelist and has no archetype.

---

## Problem

The scaffolding exists and nothing reads it.

`SessionPhase.DEBRIEF` and `SPARRING` are defined, `METERED_PHASES` excludes
both, `open_phase` refuses a metered phase through the coaching door and refuses
any phase before billing closes. The transcript persists both sides for the life
of the account on every tier (`docs/session-retention.md`). The Auditor produces
typed findings. `PanelModel.compose`'s docstring already anticipates this phase
by name: *"keeping [speech] out of here is what lets the same adapter serve the
debrief coach later, which is turn-based and has no room in it at all."*

What does not exist: anything that reads a finished transcript. No weak answers,
no coach, no sparring, no prep sheet.

Two constraints shape every decision below, and they pull in opposite
directions.

**The coach must be conversational.** §3.5 is explicit — *"a conversational
debrief, not a static dashboard"* — and §405 adds that it is real back-and-forth:
follow-ups, clarifications, the coach pushing back on a weak re-answer.

**The coach must be bounded, structurally.** `CLAUDE.md`: *"a prompt saying
'don't do general pitch review' is one jailbreak from failing, and users will
try."* An unscoped coach hands every user unlimited free pitch review and removes
the reason to pay for the panel — and open-ended *"listen and tell me how I did"*
is precisely the competitor product the wedge exists to refuse.

And one measurement governs the whole design. **#43 asked a model whether the
presenter had dodged. It said yes on 4 of 4 dodges and 4 of 4 genuine answers.**
A judgement asked of a model, in the absence of a forced choice, is not a signal.
Everything below is built around that result.

---

## Decisions

### 1. Weak answers are born when the debrief opens, and stored

Not at settlement, and not live during the room.

Settlement has four callers — the meter's session cap, the router's End, the
relay, and the reaper — and it is the billing-close path. The relay already
learned what hanging non-billing work there costs: `_keep_recording` swallows its
failures narrowly and deliberately, because *"a lost recording must not become a
lost settlement."* A multi-second model call on that path repeats the risk for a
feature that is not billing.

It would also spend a call on every room nobody comes back to. An idle-timeout
room and a client-disconnect room both settle; neither is a debrief.

So: computed on first open, written to a table, idempotent on retry. **The prep
sheet, the sparring loop and #55's calibration all read that one record**, rather
than three re-derivations that can disagree with each other about what happened
in a session the user has already read.

*Known cost of this choice:* #55 wants a difficulty signal from every session
including abandoned ones, and abandoned ones will now have none. Accepted — a
user who walked out of a room is a poor signal for how hard the next one should
be.

### 2. The model judges; code supplies what the transcript does not carry

**Reversed 2026-08-17, hours after it was taken, on the architect's push.** The
original decision put the verdict in code and left the model only a comparative
ordering of what the rules had not already caught. It was built, committed, and
is wrong. The reasoning below is the replacement; the original is preserved at
the end of this section, because the argument that overturned it is worth more
than the conclusion.

A reasoning model reads the transcript, decides which answers were weak, ranks
them, and writes the reason. Code annotates first and verifies after.

**Why the model.** Two things settle it.

*The hole was where the product lives.* No rule expressible in code can see a
fluent, specific, confidently **wrong** answer. It has a figure in it, it is on
topic, nobody presses it, and it contradicts nothing else said — so it passes
every structural check there is. But catching exactly that is what §1 means by
attacking *substance* rather than delivery, and a debrief that misses it is
scoring the shape of a conversation rather than its content.

*This is the only place in the product that can afford a good model.* Everything
else is fighting a clock: the panel has ~1.5s before the room stops feeling real
(Open Risk #3), and the Auditor's claim read already costs 0.97s and had to be
pushed a turn late to stay off the critical path. The debrief runs **once, after
the room, offline**, on a transcript of a few thousand tokens. A long think costs
cents against a room that cost ~$0.48 to hold. The constraint that shaped every
other agent decision in this codebase simply is not present here, and the first
design carried it over out of habit.

**What #43 actually proved, stated precisely**, because it had been doing more
work than it can bear. It measured a **binary** judgement, on **one utterance**,
**live**, with no alternative on offer — *"did the presenter dodge?"* — and got
yes on 4 of 4 dodges and 4 of 4 genuine answers. *"Rank these eight answers
worst-first and quote the line you are judging"* is a different task and a
different instrument. #43 still rules out asking a model whether a rule applies.
It does not rule out asking one to read.

**What code still owns, and cannot hand over.** Three facts are not in the
transcript at all, and a model given the raw text will read all three as a dodge
— correctly, because there is nothing there to read otherwise:

| Fact | Why the text cannot carry it |
| --- | --- |
| The room ended here | A hanging final question and an evasion are the same bytes |
| This line cut across the previous question | `disputed`; once written, a disputing line is ordinary panel text |
| The Auditor caught a figure moving | `chosen_by="finding"`; nothing persists a `Finding` |

So code **annotates** the transcript with what only the room knew, and the model
reads the annotated version. That is not a judgement being withheld from the
model — it is evidence being handed to it. The two columns added for the old
design are needed more under this one, not less: they are now the model's only
protection against accusing somebody of ducking a question that was taken away
from them.

**What code still owns, after.** Every weak answer must quote the transcript line
it is about, and a quote that does not match a stored line is dropped. The
category comes from a fixed vocabulary; an unrecognised one is dropped too.
Fabrication stays non-viable rather than discouraged — which is the one property
the first design had that this one must not lose.

**Accepted costs**, recorded so they are not discovered as surprises:

- The ranking will vary between runs on the same transcript. It gets measured
  against real rooms, the way #43 and #54 were, rather than assumed.
- A model having an off run can silently omit an unanswered question. #56's
  obligation rides on that never happening, so it is the first thing the
  measurement script counts.
- A per-debrief model call now exists where none did. It lands in
  `session_costs.debrief_seconds`' neighbourhood and §4.3 wants it counted.

**Measured 2026-08-17, and the argument holds.** `scripts/weakness.py` plants
five traps in one room and runs `gemini-3.7-flash` over it once, for 584 input
and ~300 output tokens:

| Planted | Result |
| --- | --- |
| A fluent, specific, **wrong** answer | Caught — *"at $180 a month, recovering a $1,200 acquisition cost takes nearly seven months rather than four"* |
| A question never answered | Caught |
| A genuinely good answer | Left alone — no false positive |
| A question a colleague cut across | Filed `dismissed`, not as a dodge |
| A question the room ran out on | Filed `not_reached`, not as a dodge |

The first row is the decision landing. Nothing structural could reach that
answer: it carries a figure, addresses the question asked, is never pressed, and
contradicts nothing said elsewhere in the room.

Two things the run corrected rather than confirmed, both recorded in the script:
the Gemini schema listed six bare category names with no meanings, so a
question a colleague interrupted came back labelled `unanswered` while its own
reason said *"you were interrupted by another panelist"* — a right reading with
a wrong label; and `CONTRADICTED` was defined too narrowly to cover arithmetic
that does not work inside a single answer, which is where the model put the
planted error and where it belongs.

**Ordering moves between runs.** Two runs, identical membership, the worst
answer ranked first and then second. Treat a single run's order as a reading of
the room rather than a fixed fact — the caution `scripts/rotation.py` already
records about its own ±2 band.

**Both vendors are implemented.** `WeaknessReader` is the only seam in the
codebase with two adapters, which is what turns the model-agnostic claim in
`CLAUDE.md` into something demonstrated rather than described. Claude was
written first, because the SDK and tool-use pattern were already present for
extraction; Gemini became the default the same day, when the Anthropic account
could not be funded. The interface cost nothing to honour and the swap took one
file. Neither has been compared against the other on quality — only Gemini has
been run.

> **The original decision, kept.** *Code sets the floor; the model only orders
> what is left.* Four properties of an answer were held to be checkable without
> judgement — nobody answered it, a panelist pressed it again, the Auditor caught
> a contradiction, and the answer contained no figure, name, date or mechanism.
> The fourth was already withdrawn during implementation: mechanism is not
> detectable without judgement, and firing on the other three would flag *"we
> rebuilt the ingestion path so retries stop duplicating rows"* as evasive — a
> false accusation, and `docs/auditor-grounding.md` prices the two errors
> against each other explicitly (*"a missed catch costs one challenge, a false
> one costs the room its credibility"*). The remaining three survive as
> annotations rather than verdicts.

### 3. The coach's scope is enforced by cite-or-redirect

Every coaching turn must name the artifact it is grounded in — a transcript
ordinal, a weak-answer id, a claim id. A turn that cites nothing is not
delivered; the redirect is sent instead.

**The bound lives in the output shape, not in a judgement about the input.**
There is no artifact to cite for material the session never contained, so the
constraint holds without asking the model to police itself — the same pattern as
the composer's citation rule and as decision 2's quote check.

Rejected: a classifier gate on each user turn ("is this about the session, or is
this new material?"). It is a binary judgement on input, which is the #43 shape;
a false positive refuses a legitimate question and reads as the product not
having listened; and it doubles the per-turn model cost on the one phase the
product gives away.

The redirect is a product moment — *"that's what the room is for"* — and **never
a paywall**. `CLAUDE.md` is explicit, and the metering boundary makes it true:
the coach is free, so refusing to review a fresh pitch is not withholding a paid
feature, it is naming which room the work belongs in.

### 4. In sparring, the check informs and the user ends the loop

§3.5 says the coach has them re-answer *"repeatedly, until the response holds."*
Something has to decide it holds.

Not the model. It is a binary judgement with no forced choice, and here the error
is asymmetric in the worst direction: false praise sends somebody into the real
room believing a thin answer landed.

So the same code check that marked the answer weak runs against the re-answer —
is the missing figure, name, date or mechanism now present, is the contradiction
gone. That tells the coach *what to say* (*"you have the number now, but you
still haven't said what changed"*). **It never announces a verdict**, and the user
always chooses to go again or move on. No pass, no fail, nobody trapped in a
loop — which matters directly under Open Risk #1.

A re-answer is fresh speech, which looks like it defeats decision 3. It does not,
because **every attempt is anchored to a stored weak-answer id**. That anchor is
required rather than usual: *"spar me on this instead"* is exactly the seam
through which free pitch review would return.

### 5. The debrief is turn-based over HTTP, not a socket

Push-to-talk: record a turn, upload, transcribe, coach responds, speech comes
back. No socket, no relay, no meter, no reaper.

Two facts point the same way. `PanelModel` already describes the coach as
*"turn-based and has no room in it at all"*, and `Product.md` §396 says the screen
is *"glanceable at best during the live phase, and fully attended only in setup,
debrief, and sparring."* **Hands-free is a property of the interrogation, not of
the product.** The phone is on the desk for the room and in the hand for the
debrief, and designing the debrief for a posture it does not have costs a relay,
an idle detector, and a reaper path for something that is not metered.

Unmetered is not free: a held socket keeps a transcription stream open and bills
for silence, which is the same failure the room's `IDLE_LIMIT` exists to catch.
Turn-based makes cost naturally proportional to use, and turns the ~20-minute
soft cap from a cost circuit breaker into ordinary copy.

Turn-based is still conversational. Turn-based is how people talk when they are
looking at the screen.

### 6. The prep sheet is a screen, and export is the share sheet

A screen in the app rendering the ranked list — the question, why the answer was
thin, and the line the user actually gave. Export renders that view to an image
on device and hands it to the native share sheet. **Nothing leaves the phone
unless the user sends it.**

Rejected: server-rendered PDF or image behind a presigned URL. It looks better
and works off-device, and it costs a rendering dependency, a retention-window
decision, and a link carrying the user's pitch content — a new disclosure surface
in a privacy policy that already carries four unresolved `[CONFIRM]` markers.

§3.5 describes the artifact as *"the 6 questions you will get, and where your
answers are thin."* The forward framing is kept and **earned by evidence**: the
sheet contains only questions this room actually asked. A question the room asked
and the user could not answer *is* a question they will get. Generating questions
the room never asked would trace to nothing, which is Open Risk #2 by name.

### 7. A room earns a debrief if the panel asked at least one question

A room that produced no question has nothing to ground a coach in, and a coach
with nothing to cite would have to invent — refused by decision 3 and by
`CLAUDE.md`.

**Refunded rooms offer a fresh room instead of a debrief.** When the provider
failed, the minutes are already back in the balance, so a restart is both cheaper
for the user and more honest than coaching them through a session the product
broke.

Rejected: a quality threshold above that — N questions, or at least one answered.
It protects the artifact most strongly and it requires telling a user their
session was not good enough to coach, which under Open Risk #1 is the single
sentence most likely to end the relationship. A thin room gets a thin debrief,
and the debrief says so plainly rather than refusing.

---

## What this does not decide

- **Difficulty calibration (#55)** stays sequenced after this phase. It reads
  ranked weak answers, which decision 1 creates.
- **The confidently-wrong answer.** Named in decision 2 and left open.
- **The soft cap's exact number.** §4.3 flags the ~10-minute average behind the
  pricing as a guess; decision 5 means we can now measure the real median before
  choosing, rather than defending 20 minutes as a cost control it no longer is.

---

## Costing, which follows rather than being decided

`session_costs.debrief_seconds` and `sparring_seconds` have existed as columns
since Phase 2 and **nothing has ever written them.** Nothing new needs counting:
`session_phase_spans` already records both phases with a start and an end, so
each is a sum over rows that already exist, materialised when a phase closes.

`RoomSpend.record` is an insert-or-add upsert keyed on `session_id`, so coach
spend arriving after settlement adds to the same row rather than fighting the
settlement write. §4.3 calls the unmetered phases the model's largest
uncontrolled exposure; it gets measured for the price of a sum.
