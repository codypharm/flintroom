# Auditor Grounding

**Status:** decided 2026-08-12. Builds in Phase 3 (Weeks 5–6) per `Product.md` §7.

Resolves what the Auditor cross-checks against when a user attaches no material —
raised by the Shark Tank case, where the pitcher walks in with nothing but their
argument and is nonetheless taken apart on their own numbers.

> **Naming.** *Auditor* here is the domain term from `Product.md` — the background
> agent that cross-checks a live transcript. It is unrelated to the `audit_log`
> module, which records money movements and security events. `CLAUDE.md` keeps
> these names apart deliberately; do not merge them.

---

## Problem

`Product.md` §3.2 makes material optional — *"Voice is the primary input"* — so a
user with no deck is a supported path. §3.3 then defines the Auditor as mapping
*"the live transcript against ingested material."* With no material, that
function has nothing to operate on.

The stakes are Open Risk #2: *"Ungrounded generic questions kill retention faster
than any UI flaw."* If the deckless session degrades to generic hard questions,
it fails in exactly the way the risk register warns about — and the deckless
session is not a rare edge case. Shark Tank is deckless. It is also the most
adversarial version of this product in existence, which is the point: **deckless
is not a degraded mode, and it must not be built as a fallback.**

## The reframe

Two jobs had been collapsed into one word.

| | What it needs | Deckless? |
| --- | --- | --- |
| **Grounding** — a challenge traces to something specific | Something the user said *or* attached | Fine. §3.3 already says "said or attached", and they are speaking claims continuously |
| **Cross-checking** — detecting that two things disagree | A reference to compare against | This is what goes missing |

So the deckless user is not ungrounded. The panel has abundant material to attack.
What is absent is a fixed reference for contradiction detection.

## Solution

**The transcript is the reference.** The Auditor holds a running set of claims the
user has made during the session and checks new speech against it, rather than
diffing against a static document.

This is what actually happens in the format that prompted the question. The sharks
have no deck either. They catch people because the numbers fail against *each
other* — you asked for $1M at 10%, and you said $50k revenue, so you just claimed
a 200× multiple out loud. No slide was involved.

Two catches follow, and they are different in kind:

1. **Self-contradiction** — comparison. The margin at minute two against the
   margin at minute nine.
2. **Implied-figure implausibility** — inference. Two statements each true on
   their own and jointly absurd.

**This runs whether or not material is attached.** Contradicting yourself is worth
catching regardless of a deck, and one Auditor with two check types avoids a
deckless fallback path that quietly receives less attention than the main one.

**Postscript (2026-08-27).** The deck-vs-speech half of this design shipped
unwired: the Auditor's memory started empty and only speech was ever compared
to speech, which the first Play-build room proved with a deck of planted
contradictions and zero findings. `written_claims` in `voice/grounding.py` now
seeds every room's Auditor with the deck's figures (`WrittenClaim` — the claim
plus its page), the deck pool is checked before the spoken one, and a deck
catch cites the page: *"Their deck says 38% for gross margin on page 5; at
2:05 they said 60%."* `room_assembled` logs `written=` beside `claims=` so a
room where the two diverge is visible rather than silent.

---

## Decisions

### Numbers interrupt live; everything else waits for the debrief

Comparing speech against a document is exact — the slide says 40%, they said 25%.
Comparing speech against speech is fuzzy. "About forty" then "thirty-eight" is not
a contradiction, it is a person talking. Neither is a mid-sentence self-correction
or a shift in emphasis.

**A false accusation is worse than a missed catch.** A panel that pounces on
rounding is not intimidating, it is stupid — and it hands the user a reason to
dismiss everything else it says.

So the bar for interrupting a live interrogation is a contradiction the Auditor can
state precisely: both figures, both moments. Qualitative findings are collected and
surfaced in the debrief instead.

Deferring costs the user nothing, which is what makes this affordable. The debrief
is unmetered (§4.1), so a finding held back is not a finding lost — it lands in the
phase where teaching actually happens, on time the user is not paying for.

### The model extracts; code computes

Every derived figure is computed in ordinary code. The model's only job is pulling
figures out of speech and into a typed claim.

This is not a prompt-level preference, it is structural. Arithmetic hallucination
becomes impossible rather than discouraged — and putting a confidently wrong number
in a panelist's mouth, live, is the one failure the grounding story cannot survive.
It also means the arithmetic is unit-testable with no model in the loop, so the
derived checks can be built and proven before the voice layer exists.

### Targeted interruption is unchanged

§3.3 already assigns the interrupter by domain: *"The CFO catches the margin
contradiction, not the Technical Skeptic."* A margin contradiction is a margin
contradiction whether it came from a slide or from minute two of the transcript.
No new rule; the domain that owns the figure owns the interruption.

---

## Architecture

The unit of work is a **claim**: a figure the user stated, captured with enough
context to compare it to another one.

A claim carries the value, its unit, what it measures, the period it covers, and
where in the session it was said. Unit and period are not decoration — most false
positives come from comparing figures that were never comparable. Last quarter's
revenue against last year's is not a contradiction, and without the period on both
it looks exactly like one.

**Extraction is universal. Derivation is domain-specific.** This split is what
makes per-segment coverage affordable, and it is also the more honest model: every
audience shares the base problem — a number was stated, and later it changed —
while what can be *inferred* from those numbers is what genuinely differs. Implied
valuation means something to a founder and nothing to a product manager.

So the per-segment claim modelling decided for v1 is built as **one extraction
layer plus a derivation pack per segment**, rather than four parallel models. That
also keeps it inside the locked architecture decision that panel internals are
*"persona + attack strategy + grounding context, as config not code"* — a fifth
segment becomes a configuration file rather than a project.

### The derivation pack contract

Each pack declares, for the segment it serves:

- **The derived figures it computes**, and the claim kinds each one requires as
  input. A derivation with a missing input simply does not fire.
- **A plausibility band per derived figure.** This is the part that is easy to
  miss: a formula alone cannot decide whether to interrupt. A 200× revenue
  multiple is absurd; 8× is a Tuesday. Without a band, the Auditor either
  challenges everything or nothing.
- **The archetype domain that owns each figure**, feeding §3.3's targeted
  interruption.

Contradiction and unit-mismatch detection come from the extraction layer and work
for every segment, including one with no pack written yet.

### Sequencing

1. **Extraction layer.** Delivers self-contradiction detection for all four v1
   audiences at once.
2. **Founder pack.** The Shark Tank case, and the sharpest derived catch in the
   product — the best available proof the mechanism works.
3. **Remaining packs** — product manager, consultant, executive.

Phase 3 already carries orchestration, turn-taking, inter-panelist disagreement,
grounded challenge generation and difficulty calibration. If it runs hot, packs
after the first can slip without the deckless story breaking, because contradiction
detection is already live from step 1.

---

## Risks

- **Latency.** Claim extraction runs during the live session, inside the ~1.5s
  budget in Open Risk #3. It is background and per-utterance, so it should hold —
  but "should hold" is precisely what that risk exists to catch. Measure it when
  the extraction layer lands, not when the panel is wired to it.
- **Cost.** `Product.md` §4.3 already reserves `auditor_invocations` in the
  `session_costs` schema. A running claim set means more invocations per session
  than a one-shot document diff, and Open Risk #4 makes every per-minute
  assumption load-bearing. This must show up in the telemetry from the first run.
- **False positives remain the failure mode to watch.** The interrupt bar and the
  plausibility bands are the two controls; both are tuning surfaces, and neither
  has been exercised against a real user yet.

## Testing decisions

Written when built. The shape is set by what would actually go wrong:

- **Claim extraction is tested without a model** — recorded transcripts in,
  expected claim sets out, so the comparison logic is provable in isolation.
- **Derived figures are tested as pure arithmetic.** This is the whole reason for
  the extract/compute split; if it needs a model to test, the split has leaked.
- **The false-positive cases are the important tests, not the true positives.**
  Rounding, self-correction, restatement, and figures from different periods must
  all fail to trigger an interruption.
- **A session with no derivation pack still catches contradictions** — the proof
  that packs are additive and that a segment without one is not unserved.
- **The archetype that interrupts is asserted**, per §3.3 — grounding correctness,
  which `CLAUDE.md` already names as required E2E coverage.

## Out of scope

- **External fact-checking.** Verifying a claim against the world, rather than
  against the user's other claims, is a different product with a different
  hallucination profile. Not v1.
- **Non-numeric contradiction detection as a live interrupt.** Collected for the
  debrief, deliberately not thrown into the room.
- **Deriving figures across segments.** A pack serves one segment; a user who
  spans two gets the pack matched at setup, not a merge.
