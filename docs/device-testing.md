# Testing the whole app on a phone

A walk through every flow that exists, on a real Android device, in the order
a person would live them. Written 2026-08-22, when everything below was built
and green in CI — what this pass answers is the question no test suite can:
does it hold up in a hand, on a desk, over real air.

**Out of scope, on purpose:**

- **Buying.** The store is `unconfiguredStore()` until the console work in
  `docs/billing-setup.md` and #96 land, so the purchase flow cannot be
  exercised. The billing *screen* is still tested below — view-only.
- **iOS.** Parked behind #99 until an iPhone is in hand.

**Two known non-bugs, so they are not reported again:**

- The grey **gear floating over the top-right corner is the Expo dev-client's
  Tools button**, confirmed by view-tree dump (#89). It is not in this
  codebase and does not exist in a release build. Drag it elsewhere if it
  covers something you are checking.
- The **transcriber turns spoken number words into digits** ("ten times" →
  "10 times") in captions and the transcript. That is Scribe, not a bug.

---

## Before you start

1. **Services on the laptop:**
   ```
   docker compose up -d          # Postgres + MinIO, from the repo root
   cd backend && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
   cd app && npx expo start
   ```
   Keep the uvicorn terminal visible — several checks below read its log lines.
2. **`backend/.env` is complete.** Every key it needs is set; the one
   placeholder is `REVENUECAT_WEBHOOK_SECRET`, which only billing needs.
   `app/.env.local` is also right as it is — `EXPO_PUBLIC_API_URL` stays unset
   in development, and the app follows the host it reached Metro on.
3. **Phone and laptop on the same Wi-Fi.** Install the dev build over USB with
   `cd app && npx expo run:android --device`, then it connects to Metro.
4. **Volume up, phone flat on the desk.** The interrogation is designed for a
   phone you are not holding; test it that way.

---

## 1. First launch and sign-in

- Fresh install (or clear the app's storage) → the app must not draw anybody's
  data; you land on sign-in / onboarding, never on a broken Home (#86).
- Sign in with Google. A failure here should name nothing about which check
  failed — that is deliberate.
- Onboarding asks its short survey, including the "when is the real one" date
  question. Answers should be skippable where the design says so.
- **The microphone is NOT requested at launch.** It is asked for on the way
  into the first room, in context (#20). If a permission dialog appears at
  first open, that is a bug.
- A new account holds **15 minutes to start**. The chip in the top bar states
  it plainly — at no point anywhere in the app should you ever see a
  depleting "N of M credits" counter.

## 2. Home — building the room

- Seat panelists: add, remove, reorder up to five. The default composition is
  mixed (champion, skeptic, neutral), never uniformly hostile.
- Open a panelist's detail page; create a **custom archetype**: the domain
  comes from our vocabulary, one free-text field. Try to make it say
  something unhinged — the text is fenced as data and must not leak into the
  panel's voice as instructions.
- Set **how hard they push** (Gentle / Firm / Relentless) and read the one-line
  explanation under it.
- Write an **audience sentence** ("a room of hospital procurement leads…").
  In the room later, the panel should be *shaped* by it but never say it aloud.
- **Attach material** via the OS file picker: a PDF, a PPTX, and a photo of a
  slide. Extraction is async — the UI should say so, not hang. An oversized or
  wrong-type file must be refused before any upload, with a plain sentence.

## 3. The live room

Start a room with a deck attached and really present something for a few
minutes. Then, one at a time:

- **Latency.** The gap from the end of your sentence to a panelist speaking
  should hold the illusion — above ~1.5 s it feels fake. Note anything worse.
- **Opening.** You get the floor first (#79); nobody attacks before you have
  made your argument.
- **Captions** track panel speech live; the active-speaker indicator and room
  temperature are glanceable from arm's length. Temperature language is
  neutral ("Convinced / Skeptical / Losing the room") — never verdicts.
- **Grounding.** Say something your own deck contradicts ("margin is 80%"
  when the deck says 60). The panelist whose domain owns that figure should
  interrupt, citing the deck — and it must be the *right* archetype.
- **Barge-in.** Talk over a panelist mid-sentence at normal volume. They stop.
- **#27 — the open measurement.** Barge in *softly*, then from *across the
  room*, and watch the uvicorn log (`voice` tag) for `vad_score` — the
  question is whether a quiet interruption survives the residual-echo
  suppressor (crosses 0.5). Record what you see; this closes or reopens #27.
- **Echo.** After asking a question the panel goes quiet. Say nothing. The
  room must not answer its own line coming back through your mic (#78) —
  a refused echo shows in the log as `echo_final_refused`.
- **Idle.** Stay silent past the warning. The room warns you first (#24), then
  ends and refunds — check the chip when you land back.
- **End.** The End control settles the room properly (#82) — the Library
  should show it immediately, with the right length.
- **Kill it.** Start another short room and swipe the app away mid-sentence.
  The sweep must settle it: no session stuck open, and no minutes silently
  charged past the kill. The chip on relaunch tells you.

## 4. Running out mid-room

Needs a nearly-empty balance. On the dev database, set your account's balance
low directly with psql (a dev-only move — production balances change through
`LedgerService` alone). Then start a room and keep going:

- The room is **never hard-cut and never shows a paywall**. The panel finishes
  its turn, the room settles, and you are handed to the debrief.
- Starting a *new* room with nothing left is refused up front, with a way to
  the billing screen — refusal before the room, never interruption inside it.

## 5. Debrief and sparring — all unmetered

- The debrief opens on the settled room with **ranked weak answers**,
  including questions that were *skipped* — and it must say whether a
  panelist waved one away or you dodged it (#56); blaming you for a
  colleague's dismissal is a bug.
- Converse with the coach. Every claim it makes should trace to the
  transcript, the findings, or your material.
- **Try to jailbreak it:** ask it to review a new pitch, fresh text it was
  never handed. It should redirect you to starting a room — "that's what the
  room is for" — never a paywall, never compliance.
- Background the app mid-thread, reopen: the thread survives (#83).
- **Spar** a fumbled answer: re-answer until it holds. No grade, no verdict,
  ever — anywhere.
- The **prep sheet** is a screen you screenshot: check it looks right *as a
  photograph*, including its way back at the foot.

## 6. Library and playback

- Every past room listed, labelled by name, date, who was seated, and length.
  Rooms past their recording window say so instead of promising audio.
- Open a room: the transcript reads as a script, the coach control sits above
  it, the player above that.
- **Play** the recording; **seek** by tapping a line's timestamp — the audio
  jumps to that moment, and it is the moment.
- **Delete the recording**: asks first, says what survives, and afterwards
  says it is gone while the transcript stays on screen.
- **Run it again** from a room's row: Home is seeded with that room's setup.

## 7. Progress

- The trend shows the whole run and opens scrolled to the newest end.
- Rooms group by the argument they are attempts at; a room row names its
  difficulty rung and opens the same detail screen the Library does.

## 8. Settings

- Every figure is your account's, not a constant (#85): tier, minutes,
  attached material count, retention window.
- The recording toggle and the disclosure text match what actually happens.
- **Account deletion last, with a throwaway account** — it is real (#53). It
  should ask hard, then leave you signed out with nothing of yours left.

## 9. The billing screen — view only

- Tap the **time chip in the top bar from each of the four tabs** → the
  screen opens; back gesture leaves it in one motion. Same from Settings and
  from a refused room start.
- The bar above it carries only the back arrow — no title, no shadow.
- It shows your balance, the packs, and the plans, with the "Buying is not
  available on this build yet" banner. Nothing here can be tested further
  until #96.

## 10. Accessibility and rough air

- **TalkBack pass:** every screen's title is announced as a heading; rows read
  their whole content, not less than the eye sees; live captions and the
  ticking counter announce sensibly rather than every second.
- **Airplane mode mid-room:** the room degrades and the affected minutes are
  refunded — never silently charged.
- Rotate, background, and low-battery-saver through a room and the debrief;
  nothing should lose state it promised to keep.

---

## When something looks wrong

Note the screen, the minute, and a screenshot, and grab the matching uvicorn
lines — the log tags (`sessions`, `billing`, `voice`, `auditor`) follow one
room across modules, and `session_costs` holds what the room actually spent.
Balance questions are answered by `ledger_entries`, which records every
movement with the reason it happened.
