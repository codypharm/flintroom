# The five release gates, run for real

`CLAUDE.md` names five flows that need E2E coverage before any release. This
directory runs them with Maestro against the real dev stack: the installed dev
client on an adb device, the running backend, the real database, the real
model and voice vendors. Nothing is mocked, which is the point — and why a run
costs real cents and real minutes.

    ./run.sh

Preconditions are the ones `docs/device-testing.md` sets up: `docker compose
up -d`, uvicorn on `0.0.0.0:8000`, `npx expo start`, and a dev client
installed and **signed in** on the device. `run.sh` checks what it can and
pushes the Kettleworks deck to the device itself. Mute the device first if
the panel talking to nobody bothers the room you are in: the rooms are real.

## What each gate proves, and where automation honestly stops

| Gate | Automated | The boundary |
| --- | --- | --- |
| 1. Setup → attach → room → settle | **Fully.** Deck attached through the OS picker, extraction to `ready`, a real room opened, the panel's opener asserted, End double-tapped, and the settle verified in the database as `user_ended`. | — |
| 2. Out of minutes → graceful handoff | **The shape.** Balance seeded to ~20s, room started, and the app must arrive at the debrief **without any tap** — never a hard cut, never a paywall. | On a silent emulator the 90s idle timeout always beats the grace cap (overdraft + 120s grace ≈ 135s), so `grace_cap` itself needs a speaking presenter. The grace ledger math is pinned by backend meter tests; the spoken version is `docs/device-testing.md` §4. |
| 3. Debrief → sparring → prep sheet | **Everything after the room.** A settled session with a Q&A transcript (and a planted dodge) is seeded; the coach's reading, the ranked entries, the armed sparring controls, and the prep sheet with its share control are all asserted against the live model. | "Answer it again" is not tapped: a re-answer is fresh *speech* (`docs/debrief-and-sparring.md` decision 4), and an emulator has nothing to say. |
| 4. Top-up → credit-toward-upgrade | **The screen.** Reached from the chip, plans rendered, the never-expire promise shown, restore present. | Purchases are blocked on #96 — this build's store refuses to sell until the Play console exists. When #96 lands, this flow grows the two purchases and the credit-toward-upgrade assertion. |
| 5. Auditor → the right archetype interrupts | **Not automatable here.** | Needs real speech contradicting an attached deck, heard by a real microphone. Scripted for a human, line by planted line, in `docs/testing-assets/pitch-script.md`. |

## Things the flows learned the hard way

- **End is a double-tap in ONE step.** The control arms on the first tap and
  forgets after 4 seconds; Maestro's between-step overhead outlives that
  window, so two `tapOn` steps re-arm forever and the room idles out while
  the flow sails on. `repeat: 2` inside a single `tapOn` is the human gesture.
- **Assert the database, not just the screen.** The first draft "passed" while
  the room settled as `idle_timeout` behind it. `run.sh` reads `end_reason`
  after every room, with a poll, because settlement is asynchronous.
- **The dev client sometimes cold-starts into its own launcher.** Every flow
  opens with a conditional that picks the dev server when that screen shows.
- **Keyboards are not worth the flakiness.** The rehearsal name is optional
  product-wide, and the one attempt to type it ended with a back-press
  exiting the app. Flows avoid the IME entirely.
