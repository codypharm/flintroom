# Making the demo video

**Written 2026-09-16. Two minutes at most.**

`Product.md` §7 week 8 asks for a high-fidelity demo video. This is the plan for
it: what to prepare, what to shoot, what to say, and the one technical trap that
can ruin a take without anyone noticing until the edit.

The on-screen labels named here were read out of `app/src/components/modules/`
on the day this was written. If a screen's copy changes, check this against it
before shooting.

---

## What the video has to prove

One thing, and everything else is supporting: **the panel attacks what you said,
using your own material.** Competitors score filler words and pace; Flintroom
checks your numbers (`CLAUDE.md` → The wedge). A video that shows a generic hard
question looks like any AI Q&A app. A video that shows a panelist catching a
figure that contradicts the attached deck shows the product.

So the answer recorded in the room is **staged, not improvised**. See step 3.

---

## Before recording

### 1. Minutes

A demo takes several rooms: rehearsal takes, the seeded history, the recorded
room. Give the demo account minutes by script, never by SQL:

```sh
railway run uv run python -m scripts.grant_minutes \
    --email <demo account> --minutes 60 --campaign demo-video --operator <you> --dry-run
```

Then without `--dry-run`. Full procedure: `docs/deployment.md` → "Minutes are
given by script, never by SQL". A second grant later needs a new campaign name
(`demo-video-2`), because each campaign grants a person once.

Only the live room spends minutes. Setup, the debrief, sparring, the Library and
Progress are free, so rehearse those screens as often as you like.

### 2. Seed the history Progress will show

Progress reads **"Nothing to compare yet"** for an account with one room, and
the debrief's comparison with last time needs a previous room too. Run **two or
three real rooms of the same rehearsal** before the recording day, using "Run it
again" from the Library so they join one lineage. Keep each short. These must be
real rooms: no invented scores, in the video or anywhere else.

### 3. Stage the contradiction

- Attach a deck with one clear figure on a slide, e.g. gross margin 28%.
- Seat a mixed panel with **The CFO** on it: its domains include margin,
  revenue, cost and runway (`backend/app/agents/archetypes.py`), so a margin
  contradiction is its to catch (`docs/auditor-grounding.md`). The Champion and
  The Technical Skeptic beside it make the mix visible.
- In the recorded room, state the figure wrongly: "our margin is 40%".
- Rehearse this off camera first and confirm the panel actually challenges it.
  If it does not, fix that before shooting. It is the video.

### 4. Test whether the recording captures the panel (do not skip)

**Run a 20-second screen recording inside a live room and play it back.**

The live room plays panel speech as voice-call audio: that is what makes echo
cancellation work (`docs/echo-cancellation.md`). Android's built-in screen
recorder generally captures media and game audio, not voice-call audio, so a
recording can show the room with the panelists silent. Not yet verified on our
build, which is why this is a test and not a rule.

If the panel is silent, two ways round it:

- **Replay the saved room (preferred).** Every room is stored as one mixed
  recording of both sides. In the Library, open the room and use **"Hear this
  room"**. Saved rooms play through the ordinary media player, not the call
  path, so the screen recorder should hear them. Test that too. This also
  shows the saved-rooms feature on camera.
- **Record the sound in the room**: a second phone or a mic beside the device,
  synced in the edit.

### 5. The phone

- Do Not Disturb on, notifications silenced, battery and signal healthy.
- Clear old test rooms out of the Library if they clutter the shot, but keep
  the seeded lineage.
- A quiet room. The panel is listening for real.

---

## The shot list

About 110 words of voiceover. Speech runs near 150 words a minute, and the
panel's own audio needs room, so the script is deliberately short. Voiceover
lines use no em dashes: they are user-facing copy.

| Time | On screen | Voiceover |
|---|---|---|
| 0:00–0:07 | **Cold open.** The panelist catching the wrong figure, from the recorded room | *(panel audio only)* |
| 0:07–0:17 | Title / intro | "Most speaking apps count your filler words. Flintroom checks your numbers. It's the room that grills you before the room that matters." |
| 0:17–0:40 | **Setup.** "What are you rehearsing?", "What's this audience like?", "Attach a deck", choosing the panel | "Tell it what you're rehearsing and who's in the room. Attach your deck, and the panel quotes your own figures back at you. Then pick who sits on it: a skeptic, a champion, someone neutral." |
| 0:40–1:08 | **The room.** "The room is listening. Take it away.", the room temperature (Convinced / Skeptical / Losing the room), captions. Cut, then the one staged question and your answer | "It's hands-free. Put the phone down and talk. Captions follow every panelist." |
| 1:08–1:35 | **Debrief.** "What held", "Where it came loose", then "Answer it again" for one re-try, and a glimpse of "Your prep sheet" | "Afterwards, the coach walks you through what held and what came loose. Then you answer the weak ones again until they stand up. Coaching never uses your minutes." |
| 1:35–1:50 | **Library.** A saved room, then "Run it again" | "Every room is saved. Pick one and run it again." |
| 1:50–2:00 | **Progress.** The seeded lineage | "And watch the same argument get stronger each time." |

The cold open is the same footage as the 0:40 section, cut earlier. Record the
room once and use it twice.

## Cutting

- Cut out every wait: the room opening, the panel thinking ("Working on it"),
  the deck being read. Those are real and fine in the product; in a two-minute
  video they are dead air.
- A jump cut inside the room is honest. A panel response spliced from a
  different room is not: the question and the answer shown together must have
  happened together.
- Burn in captions for the voiceover as well as keeping the app's own. Most
  people watch muted.

## What not to say or show

The same rules govern every outward surface, with the reasons and the voice they
belong to, in `docs/brand-voice.md`.

- **No prices, and no minute counts beyond "never uses your minutes".** Prices
  in `Product.md` §4.4 are unverified against invoices (Open Risk #4).
- **No "Investable" or "Delusional", no likelihood percentages, no "pitch
  only".** Retired framing; see `Product.md` §9 → Brand Commitments.
- **Do not describe Flintroom as scoring delivery**: pace, filler words, eye
  contact. That is the competitor product the wedge refuses.
- **No real person's name or likeness on the panel.** Panelists are archetypes.
- **Nothing a reviewer could read as a guarantee**, e.g. "you'll win the room".
