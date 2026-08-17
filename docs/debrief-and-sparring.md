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

### 2. Code sets the floor; the model only orders what is left

The Auditor's rule, applied to a second problem: *"No model here, structurally.
The model's only job is pulling figures out of speech into a typed claim; every
comparison is ordinary code."*

Four properties of an answer are checkable without judgement:

| Signal | Where it comes from |
| --- | --- |
| Nobody answered it at all | Transcript structure — a panel question with no user line after it |
| A panelist pressed it again | #43's press rule; the room judged it live, with better context than any retrospective pass has |
| The Auditor caught a contradiction in it | `Finding`, already typed and already domain-routed |

Those rank top, with no model involved. The model then ranks **only the
answered-but-questionable remainder**, and must quote the transcript line it is
judging; a citation that does not match a stored line is dropped.

> **Corrected 2026-08-17, during implementation.** This decision originally
> listed a fourth floor signal — *"the answer contains no figure, name, date or
> mechanism"*, the four specifics the composition prompt already reasons about.
> It does not survive contact with code. **Mechanism is not detectable without
> judgement**, and a check that fires on the other three would flag *"we rebuilt
> the ingestion path so retries stop duplicating rows"* — a mechanism, precisely
> answered, containing no figure and no date. That is a false accusation, and
> `docs/auditor-grounding.md` sets the priority between the two errors
> explicitly: *"a missed catch costs one challenge, a false one costs the room
> its credibility."*
>
> So the presence of a figure or a date is computed and **handed to the model as
> an observation**, not applied as a verdict. It makes the comparative ranking a
> choice between things with evidence attached rather than a matter of taste,
> which is what that call is for. The floor keeps only what is certain.

This is not #43 again, and the difference is precise. #43 asked for an absolute
yes/no with no alternative on offer, and got yes every time. Ranking the worst
three of eight is a **forced choice** — the model has to discriminate to produce
an answer at all. The residual failure is a bad ordering, not a fabricated
finding, because the quote check makes fabrication non-viable rather than
discouraged.

*Known hole:* a fluent, specific, confidently **wrong** answer looks strong to
every one of the four code signals. The Auditor catches it only when it
contradicts something else the user said. Recorded rather than solved.

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
