---
version: 1
slug: "app-src-app-prep-sheet-tsx"
primary_target: "app/src/app/prep-sheet.tsx"
related_targets: ["design-guide/pitchgo_design_system/DESIGN.md"]
---

# Prep sheet

**Mode: Operate.** Success is a presenter walking into the real room holding one
thing they can act on. Not admiration, not a shareable object — those are side
effects, and designing for them is how this becomes a poster.

## Job and audience

The presenter, alone, in the last hour before the thing they rehearsed for.
They are not exploring. They have already been through the room and the debrief;
this is the last artefact they look at, probably standing up, probably more than
once.

`Product.md` §3.5 also calls it "screenshot-friendly, which drives organic
sharing". Confirmed with the architect: sharing is a consequence of it being
good, never the design target.

## Outcome and proof

**They leave holding one instruction, not six items.** Six weak answers is a
list you skim and forget; a habit is something you can carry — *"when you don't
have the number, say you don't have the number."*

The proof is entirely the user's own session: the questions the panel actually
asked, what they actually said, and the coach's line about what was missing.
Nothing is generated for this screen. `Product.md` Principle 1 — a question
that cannot cite what the user said is the failure mode, not a lesser question.

## Selected direction

**The pattern, then the questions inside it.** Assigned by
`concept-seed.mjs --scope surface --mode operate`, seed key `8e07280c`,
candidate 7 of a 7-item grounded list ordered by resonance. My own top pick was
a flashcard deck; the roll exists to refuse that ranking rut, and the assignment
earned it on a real argument — a tally of *kinds* says something about the
presenter that six ranked items cannot.

The sheet opens with what kind of trouble they got into and how often. Each kind
opens into its questions, worst-first within the kind. A question opens to show
what they said and what was thin about it.

**The spine is fault, and this is the load-bearing rule.** Two of the six
weakness kinds are not the presenter's doing: `dismissed` means a panelist cut
across them, `not_reached` means the clock ran out. A tally that pools those
with `evasive` and `unsupported` tells somebody they failed six times when they
failed four — and undoes #56, which exists precisely so the product never
accuses somebody of ducking a question that was taken away from them. So the
groups sit under two headings, and the second is never counted alongside the
first:

- **What you did** — `evasive`, `unsupported`, `contradicted`, `unanswered`
- **What the room did** — `dismissed`, `not_reached`

The second group is still on the sheet, because §3.5's artefact is "the six
questions you will get" and those two are certainly among them. They are just
not charges.

## Scope and boundaries

One screen, production-ready, at `app/src/app/prep-sheet.tsx` with the component
in `app/src/components/modules/`. Reached from the debrief.

Inherits the established world without extending it: tokens in
`app/src/theme/tokens.ts`, which `tokens.test.ts` pins against
`design-guide/pitchgo_design_system/DESIGN.md`. No new colours, radii or type
sizes — `CLAUDE.md` forbids inventing values, and `SettingsScreen.tsx` is the
reference for how this world renders in React Native.

Untouched: the debrief screen, the coach, the tokens, the API contract.

**Anti-goals, each with the reason it is banned rather than merely disliked:**

- **No score, grade, percentage, out-of-ten, or trend.** §1 refuses
  delivery-metric scoring; a tally that acquires a number becomes the competitor
  product. Counts of kinds are description, not measurement, and must never be
  the headline.
- **No depleting counter of any sort** (`Product.md` §4.6, `CLAUDE.md`).
- **Never a paywall or upsell on this surface.** It is reached from an unmetered
  phase.
- **No cheerful encouragement and no cruelty.** §9's voice: direct and
  unsentimental, the way a good coach speaks after a hard session. The
  discomfort should feel deliberate and worth it.
- **Not a dashboard.** If it reads as a summary of performance rather than a
  thing to rehearse against, it has failed.

## States and ranges

- **Typical:** 3–6 weak answers across 2–4 kinds. Design for this.
- **One item, one kind.** Must not look broken or like an error.
- **None** — the room found nothing. A real outcome, not an empty state to
  apologise for; say so plainly and offer the room again.
- **Only "what the room did"** — every finding was a dismissal or the clock.
  The "what you did" heading must not render as a zero.
- **Long content.** A panel question can run two or three sentences and a spoken
  answer can run much longer; nothing truncates a question, ever.
- **Not debriefed yet** — the list is produced on first debrief open, so arriving
  here cold means a load. The three refusals (`session_not_settled`,
  `room_has_no_questions`, `room_broke`) each need their own words; `room_broke`
  offers a fresh room rather than an error, because the minutes are already back.

## Interaction and layout

- **Hierarchy:** pattern → kind → question → (revealed) what you said + what was
  thin. Four levels, and the fourth is behind a tap.
- **The reveal is the interaction that matters.** A question shown with its
  answer already visible is a document; a question shown alone is a prompt to
  answer it out loud. Default closed.
- **Export** renders the view to an image and hands it to the native share sheet
  — on-device, nothing uploaded, no URL, no stored object. Confirmed: the export
  carries the questions and what was thin, and **drops the verbatim answers**.
  Sharing a sheet that quotes your own worst moment is a confession nobody will
  make, and the artefact should be something a person will actually send.
- iOS-led with one shared language on Android; follow the host OS for the share
  sheet specifically (`Product.md` §9 Platform).

## Constraints

- **Data** is exactly `GET /v1/sessions/{id}/debrief` → `weak_answers[]`, each
  with `ordinal`, `question`, `asked_by`, `answer` (nullable), `weakness`, `why`.
  Generated from `contracts/openapi.yaml`; never hardcode a path.
- `asked_by` is an archetype key (`cfo`, `technical_skeptic`, `champion`) and
  needs a display name. Domain vocabulary is fixed and unabbreviated
  (`CLAUDE.md`): Panel, Archetype, Auditor, Interrogation, Debrief, Sparring.
- **Accessibility is a v1 requirement, not a pass afterwards.** WCAG 2.2 AA,
  44×44pt targets, Dynamic Type without truncating a question, and **weakness
  kind must never be signalled by colour alone** — it carries meaning here, and
  the fault/no-fault split is the most important thing on the screen.
- **A tap into sparring belongs on a question**, since #59 shipped the re-try
  loop and Principle 4 says always route into rebuilding the answer. Whether it
  appears at every level or only inside a revealed question is a composition
  decision left to the build.

## Open, for the builder to raise rather than invent

- Whether the two headings are equally weighted or whether "what the room did"
  sits quieter. It must be present and must not read as an accusation; the exact
  balance wants seeing on a screen.
- Whether the export includes the pattern summary or only the questions.
