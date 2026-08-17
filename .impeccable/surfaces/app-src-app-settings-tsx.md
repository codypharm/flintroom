---
version: 1
slug: "app-src-app-settings-tsx"
primary_target: "app/src/app/settings.tsx"
related_targets: ["design-guide/pitchgo_design_system/DESIGN.md"]
---

# Settings

**Scope:** the Settings screen, the entry point that reaches it, and the account-removal flow. Material *management* rows link out; the library and debrief are separate surfaces.

**Visitor mode:** Operate.

## Audience, job, task

Somebody between rehearsals, holding the phone and looking at it — the opposite scene from the interrogation screen. They arrive with one of four questions and leave as soon as it is answered: *how much time have I got left*, *are you recording me*, *what have you got of mine*, *how do I get out*.

Nobody browses this screen. Every visit is an errand, and the measure of success is that the errand is finished in one scroll and one tap without reading a paragraph.

Confirmed in discovery: **the entry point is in scope** (the app has four screens and no shell, so a Settings screen designed alone would have no door); **account removal is designed here and built separately** (Apple has required in-app account deletion since 2022, and Open Risk #5 wants store answers ready in advance); **plan and billing are reserved, not designed** (RevenueCat is unwired, and §413 lists tier names and prices as undecided — but remaining minutes is real today and renders).

## Chosen direction

Surface concept seed key `0ac4885a`, assigned index 7 of 7. Established world inherited, not replaced — warm off-white ground, burnt-orange primary, Hanken Grotesk, 4px baseline, oversized radii, paper-on-surface elevation. **The darkroom is interrogation-only and does not reach here.**

**The holdings inventory.** The screen opens with what Flintroom currently holds about this person, and every control sits on the thing it governs rather than in a category of controls.

Not `Privacy → Recording → toggle`. Instead: *four rooms saved, the oldest kept until 16 September*, with the switch that stops new ones on that row. *Two decks stored*, with removal on them. *Transcripts, kept while your account exists.* Then what you have — minutes remaining — then who you are, and how to leave.

**Why this product specifically.** Flintroom's whole promise is being asked the question you would rather avoid. A settings screen that leads by answering the hardest question about itself — what do you have of mine, and for how long — is that posture pointed inward. It also converts the retention decision from a policy sentence nobody reads into the first thing on screen, which is what Open Risk #5 actually needs and what a store reviewer looks for.

It earns its keep on the states, too: *"four rooms, oldest until 16 September"* and *"no rooms saved — recording is off"* are one row telling the truth in two conditions, where a conventional toggle-plus-subtitle needs the user to assemble the same fact from two places.

**Structure differs; affordances do not.** Rows, inset groups, switches, disclosure indicators and destructive styling stay standard iOS. What changes is reading order and grouping, not the controls. If it starts reading as a dashboard rather than as a settings screen that opens with a summary, it has failed.

## Anti-goals

No depleting counter, progress bar, gauge or percentage for minutes — §4.6 forbids it, and `design-guide/billing_tokens/` is the retired version of exactly this screen. No credits or tokens, in copy or in shape. No avatars or profile photography — sign-in is Apple or Google and there is no profile to edit. No dashboard, no charts, no usage history graph. No dark interrogation world. No badges, streaks or gamification (`docs/onboarding.md` rejected streaks explicitly). No settings search, no dozens of rows to search through.

## States and ranges

Realistic ranges are small and the design must not assume otherwise: 0–4 saved rooms for most accounts, 0–10 stored decks, one privacy toggle, one identity.

| State | Behavior |
|---|---|
| First run, nothing held | The inventory is empty and this is most people's first sight of the screen. It must read as reassuring and factual — nothing is stored yet, here is what will be — never as broken or as an error |
| Recording on, rooms held | Count plus the earliest expiry as a real date, not a duration |
| Recording off | Row states plainly that new rooms will not be saved; any existing rooms remain listed and playable, because turning it off does not delete them |
| Recording off, nothing held | Both halves true at once, and the row must not read as an error |
| Rooms expiring soon | The nearest date is the one shown; no countdown, no urgency styling — expiry is the promise being kept, not a warning |
| Material stored | Count and total size; source decks are already deleted after extraction, so this is claims and thumbnails |
| Minutes remaining | Whole minutes, framed generously. `GET /v1/balance` returns minutes and a boolean and deliberately nothing finer |
| Out of minutes | Stated plainly without alarm; never a paywall on this screen |
| Account removal | Destructive, confirmed, and honest about what goes — rooms, transcripts, material, and the account itself |
| Offline / request failed | Controls disable rather than lie; a toggle that appears to have flipped and did not is the worst failure this screen has |
| Largest Dynamic Type | Rows grow and wrap; counts and dates never truncate |
| Dark Mode | First-class, per `CLAUDE.md` |

## Interaction and layout

Entry point resolves as part of this work. The app currently has `index` and `room` only, so the choice is a tab bar versus a header affordance on Home — an Apple HIG top-level structural decision, not a detail. With two or three top-level destinations today (Home, Settings, and Library once it exists), a header affordance is the lighter answer and a tab bar is the one that survives Library and Debrief arriving. Decide it in the build with that trade named.

Reading order is: what is held → what you have → who you are → how to leave. Destructive actions sit last and are visually separated from everything reversible.

Every control is on its object. The recording switch belongs to the rooms row; deletion belongs to the material row; account removal belongs to the account row and to nothing else.

Feedback is immediate and honest: a toggle reflects the server's answer, not the tap. `PUT /v1/preferences/recording` returns the stored value, and that is what the row shows.

## Constraints and open decisions

- iOS is the reference platform; one shared language across iOS and Android. Safe areas, 44×44pt targets, live edge-swipe back, Dynamic Type, Dark Mode.
- WCAG 2.2 AA floor.
- Design tokens at `design-guide/pitchgo_design_system/DESIGN.md` are binding brand truth (§9). The per-screen mockups in `design-guide/` are stale — layout and density reference only, never their content model.
- Retention windows are published figures in `billing/tiers.py`: 30 days free, 90 starter, 365 pro. Show the date, not the number of days.
- The API today: `GET /v1/me`, `GET /v1/balance`, `GET`/`PUT /v1/preferences/recording`, `GET /v1/materials`, `DELETE /v1/materials/{id}`, `GET /v1/materials/limits`, `DELETE /v1/auth/sessions/sign-out`.
- **A builder must not invent:** tier names, prices, plan copy, notification settings, or any usage statistic. None of them exist.

### Unresolved

- **Account deletion has no endpoint and no task.** What is destroyed versus anonymised touches the ledger, sessions, materials, recordings and auth identities — `audit_events` deliberately carries no foreign keys so it survives, and money records have their own retention obligations. That is a real decision, not plumbing. Designed here; must be filed as its own backend task before it can ship.
- **Rooms count needs a list endpoint.** `/v1/sessions` is POST-only, so "four rooms saved" cannot be rendered today. Either a count on this screen or the library's list endpoint has to exist first.
- **Entry point:** tab bar versus header affordance, per above.
- **Whether the rooms row navigates anywhere.** It reads as a destination, but the library surface does not exist yet. Until it does the row is informational, and a row that looks tappable and is not is worse than one that plainly is not.
