---
version: 1
slug: "app-src-app-setup-tsx"
primary_target: "app/src/components/modules/PanelSetup.tsx"
related_targets: ["app/src/app/setup.tsx", "design-guide/panel_configuration/code.html"]
---

# Room Setup

**Scope:** assembling a room — who is in it, what they can attack, how hard they push — and the control that commits it. The live interrogation is a separate surface and stays dark.

**Visitor mode:** Operate.

## Audience, job, task

Somebody about to be grilled, sitting down with the phone in their hand, three minutes before they want to start. Unlike the interrogation this screen is **fully attended** — it is read, decided on, and left. Success is that the room they walk into is the room they meant to build, and that they know what it is before they press Start.

## The diagnosis this pass acted on

The screen was **three co-equal sections, each a heading over a white card** — the page-scaffold default. But it is not three chores. It is **one decision (who) with two adjustments (what they can use, how hard)**, and the type said otherwise, so the screen had no spine and read as a form.

Two structural changes followed, and everything else on this surface is downstream of them.

1. **Hierarchy.** "What they can attack" and "How hard they push" dropped from `headlineSm` to `labelLg` in `onSurfaceVariant` — field labels, which is what they are. The title stays at `headlineLg`. One primary, two adjustments, legible without reading a word. They keep `accessibilityRole="header"`: the demotion is visual, and rotor navigation should not lose two landmarks to a type decision.

2. **The room, said back.** A line composed from state — the seated archetypes in speaking order, the pressure, and the deck when there is one — sits directly above Start. Before it, the screen never once said what eight cards, a file row and three pills added up to, and Start was a button at the bottom of a scroll rather than the door into a specific room. Order is information, not flourish: the server seats archetypes as they arrive and chair one takes the floor first.

## Earlier in the same surface

- **The roster is a rail of cards**, not text rows. Measured on a device at three of three seated, the rows read as *status* and the architect concluded the panel could not be changed. It always could. A card with a face, a border and a badge is obviously a thing you pick.
- **The badge is the seat number, not a tick.** A tick says "chosen", which is less than the truth.
- **Photoreal portraits**, chosen over illustration by the architect. Generated people, never a real likeness — which is what makes them permissible under the locked archetype decision. The set is spread across age, gender and ethnicity on purpose: eight lookalike executives would be the product asserting what a CFO looks like.
- **"Tap someone to swap them out"** appears only when the room is full, because that is the only time the way out is not obvious.

## Order

**Deck, then panel, then pressure.** The sequence is not a hierarchy claim — it
is latency. Extraction is asynchronous and `setup.tsx` polls while the server
reads the file, so attaching first overlaps that wait with the decisions
somebody is making anyway instead of leaving it standing in front of Start.

The panel keeps the only heading between the title and the summary, because
sequence changed and what the screen is *for* did not. The deck and the dial
are labels; the panel is a heading.

The title moved to "Set the room" as a consequence: a screen that opens on the
deck cannot be titled with the panel's question, and "Who is in the room" is
better used where it belongs, over the rail.

## The polish pass, 2026-08-21

Three things the sections above described correctly and the code did not do.

**The rail was never full-bleed.** "Breaks the screen margin on purpose" was in
the style's own comment, and the rail sits inside a container already inset by
`space.screen` — so its `paddingHorizontal` was a *second* inset. The first card
began forty points in while the title, the deck, the heading directly above it,
the pills and Start all began at twenty, and the rail was the one element on a
strictly aligned screen that was off the margin. At the far end the viewport
stopped twenty points short of the glass, so the card that is supposed to be cut
off ended against a strip of ground and read as a row that had simply finished —
which is the "does the peek read as more" question in Unresolved, answered: it
could not, because there was no peek. A wrapper pulled back by the same inset
fixes both ends at once.

**The summary and the refusal were on opposite sides of Start.** One slot said
two ways — what the room is, or why it cannot open — and seating the first
archetype added a block above the button while removing one below it in the same
frame, so the control moved under the thumb reaching for it. They are one slot
now, above the button, which is also the order a screen reader reads: landing on
a dimmed Start used to mean being told you could not press it and having to swipe
past it to find out why.

**`header` was a slot nothing filled.** It documented Home drawing "how the last
room went, and how much time is available" above the title; Progress became a
destination of its own and the balance moved into `TopBar`, and the prop outlived
both. Removed, along with seven style objects describing the text rows the card
rail replaced.

Home's own refusal state was the other half of the pass and is not this
component's: a failed catalogue read had no Try again, on a route that never
unmounts, so one timeout at launch killed the product's first screen until the
app was. It now draws the shape `library.tsx` and the root `Unreachable` already
use, and a `SignedOut` calls the gate instead of printing a sentence.

## Telling the rail it continues

Two devices, because one is visual and one is spoken.

- **A count beside the heading** — "eight to choose from". This is the form a
  screen reader gets, and the reason it exists at all: swiping is not how
  anybody reaches these cards with VoiceOver on.
- **A directional pointer over the edge**, drawn from two borders on a rotated
  square. It points right while the rail continues right, and flips to the left
  edge pointing back once the end is reached. It never shows both: two arrows
  at once is a hand-drawn scrollbar, and at the far right the only useful
  direction is back.

The peek alone was not enough and that is measurable rather than aesthetic: the
next card is white against a warm off-white margin, so the sliver is present on
screen and invisible to a person.

## Anti-goals

No depleting counter — §4.6, and the reference mockup's "Tokens: 8" is exactly the thing. No investor-URL or profile field: that is the removed social-profile scraping, and it does not return. No pitch-only copy. No numerals for seat counts in prose — a digit on this screen reads as a score.

## Motion

**One authored moment: somebody taking a seat.** The badge overshoots and settles, the way a physical thing does when it is put down. Removal is a plain fade — taking somebody out is a correction, and a correction that performs is a screen congratulating you for undoing something. Reduce Motion cuts rather than shortens; a quick bounce is still a bounce.

Everything else on the screen is a state flip and should stay one.

## States

| State | Behaviour |
|---|---|
| Empty room | Start refuses out loud and says why; the summary is hidden, because a summary of a room nobody can enter is the screen talking past the problem |
| Full room | Unseated cards dim to 72%, never lower; the swap instruction appears |
| Deck extracting | Start refuses; the deck row shows a spinner with a spoken label |
| Deck failed | Stated on the row in `danger`, with the actions still reachable |
| No deck | **Not mentioned in the summary.** Material is an optional enrichment (§3.2) and pitching cold is supported; naming the absence turns a choice into a missing step |
| Signed out | The screen says so rather than pretending |

## Unresolved

- Whether the peek now reads as "more" needs a device. The pointer and the count carry it regardless; what changed is that the cut card runs under the edge of the glass rather than stopping short of it.
- `/v1/materials/limits` 502s without object storage (#72), so the deck row states formats without sizes. The fallback is load-bearing, not defensive.
- Custom archetypes have no endpoint (#65) — the author card is a statement, deliberately not a control.


## The way back to an empty room, added 2026-08-22

The architect asked for a reset on a device. It is one control on the title row,
and four things about it were decided rather than defaulted.

**It is absent until there is something to clear.** `built` is derived from the
props that are already there — seating, name, note, deck — rather than tracked
as a flag, so it cannot disagree with the screen. That is what lets it sit
beside the heading: on a fresh room there is no disabled control next to the
title saying what the screen is for.

**It arms rather than fires**, the shape End already uses on the interrogation
screen. There is no undo behind it: the deck is destroyed on the server and the
note is a paragraph somebody wrote about a room they are walking into. The label
changes from "Reset" to "Tap again", and the ink to `danger` — two channels, so
nothing is carried by colour alone. It forgets after four seconds, because an
armed control that stays armed is a trap set for whoever touches the screen next.

**It does not touch the rung.** Difficulty is the *account's* setting, stored
server-side the moment it is tapped, and it outlives this room — a reset that
moved it would silently undo something the next rehearsal inherits. What does go
is `pinned`, the pressure a re-run carried in from the Library: a room that no
longer repeats anything should show the account's rung rather than a rehearsal's.

**It is text, not a bordered control.** `Library`'s "Run it again" needed the
outline because it *starts a metered room* while sitting beside a bare tap area.
This one spends nothing and undoes work; the burnt orange on this screen belongs
to Start, and a reset in the same weight would put discarding a room level with
building one.
