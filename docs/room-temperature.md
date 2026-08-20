# Room temperature

Resolved design for #74, **not built**. Parked 2026-08-20 in favour of
grouping rooms by what they rehearse, which answers the question the gauge was
being asked to answer and answers it better. Recorded so the decisions below
are not re-litigated when it is picked up.

State today: nothing computes, sends or draws it. `room_temperature` occurs
once in the repo — `connection.test.ts`, as a *hypothetical* event proving an
unknown message type cannot kill a live room on an old build.

## 1. It reads the room, not the presenter

The product refuses to score people: #59 forbids a verdict on a sparring
answer, `PrepSheet` "puts no grade, mark, or verdict on a room", and
`difficulty-calibration.md` decision 5 says a rung rendered on a debrief turns
the screen into a score. A live gauge is the same species and would be the only
one in the app, at the most vulnerable moment, against Open Risk #1.

What reconciles it: "losing the room" is a statement about where the panel is,
not a mark against the person. Reading a room is a skill a presenter is meant
to develop, and a real board gives that signal constantly through faces and
posture. Audio-only takes it away; the gauge gives back what the medium
removed.

This constrains the copy. Every label describes **the panel's state**, never
the presenter's performance. "Losing the room" passes. "Struggling" does not.

## 2. A gauge, and unnumbered

`Product.md`:94 says gauge, and for a hands-free screen a gauge beats words:
reading three words costs a train of thought mid-sentence, where a position or
a colour is perceived peripherally. Words survive as the accessibility label,
because a purely visual gauge is unusable to a screen reader and `CLAUDE.md`
puts WCAG 2.2 AA in v1.

No percentage, no 0–100, no tick marks implying a measurable quantity — those
are the retired "Avg. Likelihood %" returning. A needle with no numerals is
directional. A needle at 34% is a grade.

Motion is slow and damped: a gauge that jumps pulls the eye, which is the
opposite of glanceable. Reduce Motion cuts rather than shortens, as
`ArchetypeCard` already does.

## 3. Warmth requires positive evidence, never the absence of trouble

The first draft warmed the needle when an exchange passed without the Auditor
catching anything. The architect caught the flaw: the Auditor catches
contradicted **figures**, so somebody who states no figures cannot be
contradicted — and the cheapest way to warm the gauge would be to say nothing
checkable. The product exists to attack exactly that.

So warmth is earned by checkable substance that survived checking:

| What happened | Needle |
| --- | --- |
| Stated a figure, Auditor found no contradiction | warms |
| Said nothing checkable | **parks** — nothing risked, nothing learned |
| Stated a figure the material contradicts | cools |
| Same domain pressed a second time | cools |

## 4. Only what happened out loud may move it

If the needle moved, something occurred in the room the presenter could point
at. No hidden inference. Same standard `Product.md` sets for challenges under
Open Risk #2, applied to the gauge — and it is what makes the panel pressing
again the honest source of cooling, since that is the room's own judgement,
already audible.

## 5. The harm is asymmetric, so the top is hard

Too cold and somebody works harder. Too warm and they walk into a real board
over-confident because we told them they were convincing — worse than anything
the panel could say. "Convinced" needs sustained surviving substance across
several exchanges, and drops on the first contradiction rather than decaying.

## 6. Live only, never persisted

It is the last sample of a noisy signal taken at whatever second End was
tapped; the same room two exchanges later reads differently. Difficulty
escalates, so a needle from a Relentless room is not comparable to one from a
Gentle room, and unlike Progress's bars a needle carries no rung. And
`Progress.tsx` already refuses this in as many words: "a single number standing
for a run is exactly what somebody would start optimising instead of their
argument."

Whether a presenter is improving is answered by grouping rooms by what they
rehearse — see the lineage work that parked this.
