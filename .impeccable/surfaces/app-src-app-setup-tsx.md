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

- The rail's last card sits close to the right margin at three seats; whether the peek reads as "more" needs a second device.
- `/v1/materials/limits` 502s without object storage (#72), so the deck row states formats without sizes. The fallback is load-bearing, not defensive.
- Custom archetypes have no endpoint (#65) — the author card is a statement, deliberately not a control.
