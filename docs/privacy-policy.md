# Privacy Policy — working draft

**Status: derived from the implementation, 2026-08-17. Not yet reviewed by a
lawyer, and not publishable as written.**

This is the disclosure text assembled from what the code actually does, so that
App Store review (Open Risk #5) is answered from behaviour rather than from
intent. Every retention figure below is enforced somewhere and testable; the
places that need a human decision or a vendor's written answer are marked
**[CONFIRM]** and must not go out unresolved.

Written now rather than in submission week deliberately. `Product.md` §7 gives
Week 8 a week of slack for review, and a policy drafted then would be describing
a system nobody could still change.

---

## What Flintroom collects

**Your voice, during an interrogation.** The microphone is open for the whole
live session, because the panel interrupts and has to hear you to do it. Audio
is streamed to a speech-to-text provider as you speak.

**What was said, as text.** Both sides of the room — your words and the panel's
— are stored as a transcript. This is what the coach is grounded in during
debrief and sparring; without it there is no way to be told which of your
answers was weak.

**Material you attach.** PDFs, PowerPoint files, pasted text, and photographs of
slides or whiteboards. These are read once, and the claims and figures found in
them are kept. **The file itself is deleted as soon as it has been read** — what
survives is the extracted claims and a single thumbnail.

**Your account.** Sign-in is through Apple or Google. Flintroom stores the
identifier they return and nothing else about you: no password, no profile, no
contacts, no address book.

**How much you used.** Session start and end times, minutes consumed, and what
each session cost to run. This is how billing works and how the service is kept
solvent.

Flintroom does **not** collect video, does not analyse your face or body
language, and does not build a profile of you from anywhere outside the app.

---

## How long it is kept

| | Kept for |
| --- | --- |
| **Recording of a room** | 30 days (Free), 90 days (Starter), 12 months (Pro) |
| **Transcript of a room** | As long as you have an account |
| **Attached material** | The source file: minutes. The extracted claims and thumbnail: until you delete them |
| **Account and usage records** | As long as you have an account |
| **Billing and money records** | [CONFIRM] — kept after account deletion, no longer linked to you, where tax or accounting law requires it. The period depends on jurisdiction and needs an answer before publication |
| **A deleted account** | Seven days before the purge runs; signing in during them cancels it |

A session that fails technically is refunded and **retains no audio at all**.

Recordings are deleted by a scheduled process that records each deletion, so
that "your recording was deleted on this date" is a question with an answer
rather than an assurance.

If you move between plans, the window that applies is the one for the plan you
are on now. Downgrading shortens it, and rooms past the shorter window are
removed at the next sweep.

---

## What you can do about it

**Stop rooms being recorded.** A switch in Settings. It takes effect on your
next room; rooms already saved are not deleted by it, because they were saved
under a disclosure you accepted — removing them is a separate, deliberate act.

**Delete a room's recording.** Any room, at any time. Open it from the Library
and the control is at the foot of the transcript — which is where it is on
purpose, because **what was said stays**. Only the audio goes. The two are kept
separately and deleting one does not take the other, so the room remains
readable and the coach can still go through it with you.

**Delete attached material.** Any time, in Settings, under Material. It
destroys the file, everything extracted from it, and the thumbnail. Rooms you
already ran are unaffected — running one of them again simply will not be
grounded in it. The one refusal is a deck a room you are currently in is
standing on: the panel is cross-checking what you say against it, so we ask you
to end that room first.

**Delete your account.** In Settings, and it takes seven days.

Asking schedules the deletion and signs you out everywhere. For the next seven
days the account is hidden rather than gone, and **signing in during that time
cancels the deletion** — we say so plainly when it happens, rather than quietly
restoring an account you meant to lose. After seven days a scheduled process
destroys your rooms, their transcripts and recordings, the material you
attached, your settings, and the record linking this account to your Apple or
Google sign-in.

What survives is your billing history, stripped of any link to you: once the
sign-in record is destroyed, the account identifier maps to nobody, and what
remains is a row of numbers we are required to keep (see below).

You are told that rooms are saved, and for how long, before your first
interrogation begins — on a sheet you have to pass through, ahead of the
microphone permission prompt.

---

## Who else sees it

Flintroom is built on other companies' services, and the live parts of a room
necessarily pass through them.

| Provider | What reaches them |
| --- | --- |
| **ElevenLabs** | Your speech, to turn into text; the panel's lines, to turn into speech |
| **Google (Gemini)** | The transcript of the room in progress, to decide who speaks and what they ask; the contents of material you attach, once, to extract its claims; the transcript again afterwards, to work out which answers were weak and to hold the debrief |
| **Anthropic (Claude)** | Nothing today. Configured as the alternative for the two model tasks above, and this row becomes accurate the moment it is selected |
| **Supabase** | Hosts the database. Flintroom is the only thing that reads it; the app holds no database credentials |
| **Cloudflare R2** | Stores recordings and thumbnails |
| **RevenueCat** | Subscriptions and purchases [CONFIRM — not yet integrated] |

**[CONFIRM] Whether any of these providers may train models on what passes
through them is a contractual question, not a technical one.** It has to be
answered from each vendor's current terms and any agreement signed with them
before this section can say anything about it. Do not write "your data is never
used for training" without that in hand — it is the single sentence most likely
to be both expected and unverifiable.

Flintroom does not sell your data, and does not share it with advertisers.

---

## Things this policy deliberately does not say

Recorded here so the omissions are choices rather than oversights.

- **No claim about training.** See above.
- **No specific sub-processor list beyond the table.** Hosting and error
  reporting are not decided yet.
- **No international transfer language.** [CONFIRM] Depends on where the
  database and object storage are finally hosted, which
  `docs/deferred-scale-work.md` settles as Cloudflare R2 for storage and leaves
  open for the database region.
- **No children's provision.** [CONFIRM] Flintroom is a professional rehearsal
  tool and the App Store age rating has not been set.

---

## Where each figure comes from

So that this document can be checked against the system rather than trusted.

| Claim | Enforced by |
| --- | --- |
| Retention windows | `backend/app/modules/billing/tiers.py` → `RECORDING_RETENTION_DAYS` |
| Deletion actually happens | `backend/app/modules/sessions/retention.py`, swept on a schedule |
| Deletion is provable | `audit_events` rows: `recording_expired`, `recording_deleted` |
| A failed room keeps nothing | `backend/app/modules/voice/relay.py` → `_keep_recording`, derived from `REFUND_REASONS` |
| The source file is deleted after reading | `docs/ingestion.md`, `backend/app/modules/ingestion/service.py` |
| Recording can be turned off | `backend/app/modules/sessions/preferences.py`, read before a room opens |
| Attached material can be destroyed | `backend/app/modules/ingestion/service.py` → `delete`, reachable at `app/src/app/material.tsx` |
| A recording can be destroyed on request | `backend/app/modules/sessions/router.py` → `delete_recording`, reachable at `app/src/app/rooms/[id].tsx` |
| Deleting a recording keeps the transcript | `backend/app/modules/sessions/retention.py` → `delete` touches `session_recordings` only |
| The disclosure precedes the microphone prompt | `app/src/lib/consent/entry.ts` |

The full reasoning behind these decisions is in `docs/session-retention.md`.
