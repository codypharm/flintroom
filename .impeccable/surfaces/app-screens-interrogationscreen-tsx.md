---
version: 1
slug: "app-screens-interrogationscreen-tsx"
primary_target: "app/src/components/modules/InterrogationRoom.tsx"
related_targets: ["design-guide/interrogation_dashboard/code.html"]
---

# Live Interrogation Screen

**Scope:** the live interrogation screen and its states only. Panel setup, debrief, and sparring are out of scope and stay on the light surface.

**Visitor mode:** Operate.

## Audience, job, task

A presenter mid-argument with the phone flat on the desk, talking to a room that isn't there. Hands-free, eyes up, under real pressure. The screen answers three questions in under a second of peripheral glance — who is on me, how is it going, what did they just ask — and otherwise gets out of the way. Success is that it never once made them stop speaking to work something out.

Confirmed in discovery: **glance-only, one control** (End, and nothing else); **captions as current line, large** (one treatment serves both the glancing user and the deaf/HoH user — no separate accessibility mode); **the Auditor is silent** (its finding arrives as a panelist interrupting; receipts appear in debrief).

## Chosen direction

Surface concept seed key `54b8fcc1`, assigned index 5 of 7 (split field). Material world fused from challenger `signals-instruments-darkroom-safelight-bay`.

**Split field mapped to physical distance.** The phone lies flat, so the top of the screen is farther from the eye than the bottom.

- **Far field (top ~55%) — the room.** Archetypes as prints in developer trays: silver-gray fields on the safelight ground. The speaker's tray develops — deepens toward full contrast while they speak, recedes after. No faces, no avatars, no names competing for attention.
- **Near field (bottom ~45%) — the record.** The live line in large type, silver-white, emerging word-by-word as speech arrives. The single End control sits at the nearest edge, the one enamel-white object on screen, findable by position without looking.

**Darkroom under safelight.** Ground is near-black with an amber cast — a dark room with the light on, not an OLED void. A darkroom is the one room designed so you can see what you need without the light ruining the work, which is this screen's exact problem. Amber is the deepest reading of the committed burnt-orange primary, so this extends the identity rather than replacing it. Color strategy: Committed — amber carries the ground's cast and active elements; the caption field stays achromatic so legibility never negotiates with mood.

**Cross-surface reach.** Setup, debrief, and sparring stay warm off-white. The interrogation is the dark room: you go in, and you come out.

**Memorable moment — the developing challenger.** In a darkroom a print shows itself before it is ready. While one panelist speaks, a second tray begins to emerge in the far field. That is "who is about to challenge": the dread of a real room with no alarm, badge, or sound. Peripheral and detail-free by design.

**Room temperature is the safelight itself.** Convinced warms and lifts the amber; Skeptical is neutral; Losing the room cools and dims toward gray. No gauge, no needle, no number — perceivable without looking directly at it, which is the only way a hands-free user perceives anything.

**Type.** Hanken Grotesk carries the caption (the screen's only real content, and the brand's display moment); SF handles small utility labels per HIG. Dynamic Type scaling must be wired explicitly for the custom face in React Native, not assumed.

## Anti-goals

No waveform — it visualizes amplitude, not argument, and it is the reflex every voice UI reaches for. No score or percentage. No depleting counter or bar. No Auditor flags. No faces or avatars. No chat bubbles. No gamification. No pause.

## States

Panel size 1–3 archetypes. Interrogation up to 12 minutes.

| State | Behavior |
|---|---|
| Pre-roll | Mic permission primed with a plain reason; recording disclosure honest and visible |
| User speaking | Trays quiet, safelight steady. The current question stays pinned in the near field — people forget the question under pressure |
| Panelist speaking | Tray develops, line emerges word-by-word |
| Barge-in | Panel yields; tray recedes mid-development. Must read as permitted, never as a penalty |
| Targeted interruption | Second tray snaps to full development, first recedes |
| Auditor catch | No visual state. The interruption is the reveal |
| Minutes exhausted | Nothing changes on screen. No paywall, no banner, no color shift — settle after the panel finishes |
| Session limit | Spoken handover into debrief; screen transitions, never a modal |
| Provider degraded | Honest, non-alarming; affected minutes refunded |
| Idle/silence | Warn before auto-ending and refunding |
| Reduce Motion | Development crossfades instead of emerging |
| Largest Dynamic Type | Line reflows; never truncates a panelist's question |

## Constraints

One touch target on the entire screen. Safe areas respected; nothing under the Dynamic Island or home indicator; left-edge back gesture stays alive. Motion is the darkroom's own — continuous emergence, never a typewriter tick, never a pulse.

## Unresolved

- Whether the user's own speech is captioned back to them during interrogation. Recommendation: no — it invites reading yourself instead of arguing. Not yet decided.
- On-screen archetype naming.
- Recording retention window (open product decision).
- **The world is committed on paper and unproven in pixels.** Honest risk: if it reads as moody rather than as an instrument, it fails. Second risk: the developing-challenger signal could become something users watch instead of arguing — mitigated by keeping it far-field and detail-free, but it is the first thing to test with real users. Next step is a comp of this screen, which also settles archetype depiction for panel setup to inherit.

---

## Built, 2026-08-19 (#41)

`app/src/components/modules/InterrogationRoom.tsx` + `Tray.tsx`, behind
`app/src/app/interrogation.tsx`. Reached only from Start on `/setup`. The
instrument screen it replaced (`app/src/app/room.tsx`, a pasted dev token and an
inline `POST /v1/sessions`) is deleted.

**Shipped from this brief:** the split field, the trays, the single End control,
one caption as the near field's content, the dark ground.

**Deferred, each with its own task and its reason:** room temperature as the
safelight (#74 — now built, see below); the developing challenger (#75 — now
built too, see below).
**Nothing else was allowed to colonise the ambient ground,** so #74 has
somewhere to land: the floor indicator is at the nearest edge and the speaker
indicator is in the trays.

### Where the built screen departs from this brief, and why

- **The line appears whole, not word by word.** The wire carries finished
  utterances and no word timing — the caption is put on the socket *before* its
  own audio (`orchestrated.py:726`) — so emergence would be the phone guessing
  a speech rate and drifting against the voice. Theatre on the one screen that
  has to be trusted at a glance, and worst for the reader captions exist for,
  who would be paced by a soundtrack they cannot hear.
- **The speaker is named in text, beside the line.** The brief's "no names" was
  about the far field and still holds there. But caption standards want the
  speaker identified wherever more than one person speaks, and at the trays'
  intended subtlety they fail WCAG 1.4.11 as the sole carrier of who is asking.
  Naming it in text releases the trays to stay quiet.
- **A floor indicator was added**, at the architect's request: the nearest edge
  lifts while speech is present, and says so when the presenter is too quiet to
  be transcribed. **Not a level meter** — the anti-goal stands, and the reason
  is the viewing condition: a moving object is the most attention-capturing
  thing possible in peripheral vision on a screen whose premise is that nobody
  looks at it, and at an oblique angle on a desk it cannot be read as a quantity
  anyway. Three states, in `app/src/lib/audio/hearing.ts`.
- **The room says the floor is yours before anyone speaks.** Not in the brief's
  state table, and load-bearing: the panel does not open the room
  (`orchestrated.py:294`), and the meter starts when the channel does — so a
  confused silence is billed at 15-second ticks until the idle timeout at 90.
- **End confirms in place** — one tap arms it, the second ends. One touch
  target, no modal, no hidden gesture, and a brushed thumb cannot end a
  rehearsal that has no resume.

## The safelight, built 2026-08-22 (#74)

The brief's *"Convinced warms and lifts the amber; Skeptical is neutral; Losing
the room cools and dims toward gray"* is shipped. Four things it turned out to
require, each of which could have gone the other way.

**It is not a model call, and that is a measurement.** The obvious build asks a
model how the room is going, once a turn. Asked *"did the presenter dodge?"* a
model said yes on 4 of 4 dodges **and** 4 of 4 genuine answers (#43) — the same
finding that made the difficulty dial two integers rather than an adjective. A
gauge is that question in a friendlier coat, asked eight to fifteen times a room
on the *metered* path whose margins §4.3 has not reconciled against an invoice.
So the band is read from `Said.chosen_by == "finding"`: the Auditor having caught
a figure that moved or a claim contradicting an earlier one. An event, not an
opinion, and the same signal `weakness.py` already ranks on.

**It errs warm, deliberately.** #74 names the harmful failure — telling somebody
they are losing the room while they are doing well, mid-session, when they cannot
argue back. So cooling takes two catches inside four challenges and warming takes
six consecutive clean ones: being caught is evidence, not being caught is the
absence of it, and absence is cheap early in a deckless room where the Auditor's
reference is still accumulating. Disputes are excluded entirely, which is #56's
rule applied live — a question waved away by a colleague is not the presenter's
fault.

**Every route between the extremes passes through neutral**, which is what holds
a twelve-minute room to two or three changes rather than one per turn. It also
means the safelight always crosses the resting ground rather than swinging.

**Warm is warmer without being lighter.** "Lifts the amber" first read as raising
lightness, and lightness is the one thing this ground cannot spend:
*Interrogation Tray Lit* sits at 3.05:1 against the neutral ground, four
hundredths above the WCAG 2.2 non-text floor. `hsl(20, 26%, 10%)` — the obvious
warm — measures **2.84:1**, which would have shipped a screen whose accessibility
failed only when things were going *well*. Warming by chroma at constant
lightness gets the read and moves contrast the right way: the warm ground
measures 3.08:1 and the cool one 3.14:1. Both are now in DESIGN.md.

**Drawn as two casts over the neutral ground, not three grounds.** React Native
cannot drive `backgroundColor` on the native thread, and this is the screen that
must not drop a frame; opacity is native, and at full opacity each cast *is* its
token exactly. Hidden from the accessibility tree on purpose — a live region
reading "losing the room" over a panelist mid-question would heckle somebody who
cannot hear it coming, and the anti-goals forbid a score here in any form. The
debrief carries the same finding in words with the questions attached, which is
what makes it evidence rather than a verdict.

**Still open:** whether the band belongs in the debrief as well. Argued against
for now on the grounds that the debrief already ranks weak answers from the same
underlying record, in words — a coarser second version of one fact, free to
disagree with the first, is the argument `context.py` already makes about storing
a finding's summary beside the line that states it.

### Resolved from the Unresolved list

- **The user's own speech is still not captioned back.** Unchanged, and now
  structural: there is no event for it and `events.py` says adding one is a
  decision rather than a completion.
- **On-screen archetype naming:** resolved. Titles from `/v1/archetypes`, in the
  near field only, never on a tray.
- **Recording retention window:** resolved. Read per account from
  `GET /v1/preferences/recording` and stated in the disclosure sheet, which
  `/interrogation` presents via the tested `enterRoom` sequence.
- **"Committed on paper and unproven in pixels" still stands.** It has now been
  built and typechecked and tested; it has not been seen on a device.


## The developing challenger, built 2026-08-22 (#75)

The brief's memorable moment — *"In a darkroom a print shows itself before it is
ready... the dread of a real room with no alarm, badge, or sound"* — is shipped.
Four things it turned out to require.

**The staging in the brief does not exist, and what replaced it is stronger.**
The brief pictures a second tray emerging *while one panelist speaks*. The turn
cycle is presenter → panelist → presenter → panelist, so nobody is speaking when
the next challenger is chosen. The tray emerges into the silence right after the
presenter stops: they have just finished, the room is quiet, and they can see
who is coming. The only cases matching the brief's literal picture are barge-in
and #54's disagreement turns.

**The window is ~1.2 seconds, and it is measured rather than hoped for.**
`docs/panel-orchestration.md` puts composition at 0.82s and synthesis at 0.38s,
and #42 already moved selection off that path. `DEVELOP_MS` is 1400, so the
print is still coming up as the voice starts — which is what "shows itself
before it is ready" actually looks like.

**It cannot lie, and that is structural rather than careful.** The ticket
deferred this out of #41 because the Auditor's finding outranks the early
selection, so a tray raised from routing alone could develop for somebody who
never spoke. The fix was not a rule about when to announce: it was extracting
`who_takes_the_floor` so the announcement and the turn read the *same* decision.
There is one spelling; a test compares what was announced against who spoke.

**A print coming up, not a print lifted out.** Speaking slides a seat to the
middle of the table and grows it. This does neither — the face rises part-way
out of the safelight, in place, in the far field. Two seats equally lit is the
one thing the trays must never say, so the two opacities are multiplied rather
than raced, and an archetype who is both (two turns in a row) reads as already
developed rather than flickering.

**Still open, and named in the brief:** whether this becomes something users
watch instead of arguing. It stays far-field, detail-free, and silent to a
screen reader; it has not been seen on a device by anybody.

**And one thing is now knowable that was not.** The ticket wanted the
supersession rate *"measurable from `chosen_by` on the transcript"*, and it was
not: `interrogate` discarded `routed` unread whenever a finding existed, so "the
Auditor decided" and "the Auditor overruled somebody" were the same record. The
`panel_turn` log line now carries `superseded`, so the rate at which a tray
swaps under a presenter's eye can be counted from a real room rather than
guessed at.
