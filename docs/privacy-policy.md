# Privacy Policy — working draft

**Status: derived from the implementation, 2026-08-17; re-derived 2026-08-27
after billing, custom panelists and the coach shipped. Not yet reviewed by a
lawyer, and not publishable as written.**

This is the disclosure text assembled from what the code actually does, so that
App Store review (Open Risk #5) is answered from behaviour rather than from
intent. Every retention figure below is enforced somewhere and testable; the
places that still need a human decision are marked **[CONFIRM]**, dashboard
work is marked **[ACTION]**, and wording that only counsel can bless is marked
**[LAWYER]**. None may go out unresolved.

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

Each line also carries **how many seconds into the room it began**, so a finding
can point at the moment it happened rather than at a recording starting from the
top. This is a number about a line, not a copy of it, and it is recorded whether
or not you have rooms saved — turning recording off stops audio being kept, and
the transcript is kept either way, so an offset on a line we are already keeping
claims nothing further about you. Rooms that ran before this existed have none,
and nothing was invented for them.

**That you opened the app.** One event named `app_open` is recorded per
launch while you are signed in — a name, your account, and a time, and
nothing else. It exists to answer whether people come back, it never contains
what anyone said, and it stays in Flintroom's own database rather than going
to an analytics company. Any future event is subject to the same shape: a
short fixed name, no free text.

**Material you attach.** PDFs, PowerPoint files, pasted text, and photographs of
slides or whiteboards. These are read once, and the claims and figures found in
them are kept. **The file itself is deleted as soon as it has been read** — what
survives is the extracted claims and a single thumbnail.

**What you write about the room you are facing.** Before a room opens you may
describe the audience in your own words — "my VP hates anything that adds
headcount". It is optional, it is capped at a paragraph, and it is stored on
that one room rather than on your account, so a different rehearsal never
inherits it. It is sent to the model that writes the panel's questions, which
uses it to decide what to press on; **the panel never reads it aloud**, and
nothing in it may be stated back to you as a fact. It is never written to a log.

Flintroom asks you for this rather than looking anybody up. Nothing about the
people you name is fetched from anywhere — not from a social network, not from
a search engine, not from any public profile. The only thing the panel knows
about your audience is what you typed.

**Panelists you write.** You may author a custom panelist — a name, a title,
and a description of who they are, in your own words. It is stored on your
account until you archive it or the account is deleted, and it is sent to the
model that writes that panelist's lines whenever you seat them in a room. Like
the audience note, it is treated as material rather than as instructions.

**What you say to the coach.** The debrief and sparring are conversations, and
both sides of them are stored with the room they belong to — the coach's
walkthrough, your questions, and each re-answer you attempt. This is what lets
you reopen a debrief later and find the conversation where you left it.

**Your account.** Sign-in is through Apple or Google. Flintroom stores the
identifier they return and, when the provider supplies one, the email address
on that sign-in — it is what the account-deletion confirmation is sent to.
Nothing else about you: no password, no profile, no contacts, no address book.

**How much you used.** Session start and end times, minutes consumed, and what
each session cost to run. This is how billing works and how the service is kept
solvent.

The app does **not** collect video, does not analyse your face or body
language, does not carry an advertising or analytics SDK, and does not build a
profile of you from anywhere outside the app. The marketing site is a separate
surface and is described under **The website** below.

---

## How long it is kept

| | Kept for |
| --- | --- |
| **Recording of a room** | 30 days (Free), 90 days (Starter), 12 months (Pro) |
| **Transcript of a room** | As long as you have an account |
| **What you wrote about the audience** | As long as you have an account, on the one room it was given to |
| **Attached material** | The source file: minutes. The extracted claims and thumbnail: until you delete them |
| **Debrief and sparring conversations** | As long as you have an account, with the room they belong to |
| **Panelists you write** | Until you archive them; destroyed with the account |
| **Account and usage records** | As long as you have an account |
| **App-open events** | 12 months, then deleted by a scheduled sweep; deleted immediately with the account |
| **Billing and money records** | For as long as tax and accounting law requires, and after account deletion no longer linked to you — once the sign-in record is destroyed the account identifier maps to nobody. [LAWYER] Confirm the wording carries in the business's jurisdiction; the mechanism is built and needs no answer, only the sentence does |
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

With it off, no audio is held at any point — not gathered and later discarded,
but never accumulated. The transcript is still kept, on every plan, because the
debrief has nothing to work from without it.

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
| **Google (Gemini)** | The transcript of the room in progress, to decide who speaks and what they ask; what you wrote about the audience, if anything, to decide what to press on; the contents of material you attach, once, to extract its claims; the transcript again afterwards, to work out which answers were weak and to hold the debrief |
| **Anthropic (Claude)** | Nothing today. Configured as the alternative for the two model tasks above, and this row becomes accurate the moment it is selected |
| **Supabase** | Hosts the database. Flintroom is the only thing that reads it; the app holds no database credentials |
| **Cloudflare R2** | Stores recordings and thumbnails |
| **RevenueCat** | Your purchases and subscription state, keyed to your account identifier, so that what you bought follows your account rather than your device. Card details never reach Flintroom or RevenueCat — Google Play (and later the App Store) takes the payment |
| **Resend** | Your email address and one message, only when you ask for your account to be deleted — the confirmation carrying the date the seven-day window closes. Nothing else is ever emailed from the app backend |

**Whether these providers may train models on what passes through them** was
checked against each vendor's published terms on 2026-08-27, and comes down to
two account settings rather than open questions:

- **Google (Gemini): decided by billing tier.** On the paid API tier Google
  states that prompts and responses are not used to improve its models; on the
  free tier they may be, and human reviewers may read them. **Done — the
  production key was confirmed on a paid billing account on 2026-08-27.**
- **ElevenLabs: on by default, off by a switch.** Their terms allow content to
  be used to improve their services unless the account opts out, in the
  dashboard's *Data use* menu. **Done — the opt-out was flipped on the
  production account on 2026-08-27.**

Both were done on 2026-08-27, so the published page may — and now does — say:
*"our speech and model providers are barred, by the service tiers and settings
we use, from training on what passes through them"* — cited to the tier and
the setting rather than to hope. If either the ElevenLabs account or the
Gemini billing arrangement ever changes, `web/src/pages/privacy.html` carries this
sentence and must change with it.

Flintroom does not sell your data, and does not share it with advertisers.

---

## The website

`flintroom.app` is a static marketing site with eight free calculators on it. It
carries Google Analytics. The app does not, and `docs/analytics.md` records why
the two are answered differently: counting strangers is marketing's job and
lives with the website, while the app measures itself in our own Postgres.

What it collects is what GA4 collects with no configuration: which pages were
opened, approximate location derived from the IP address, device and browser.
It runs in Consent Mode with `analytics_storage` defaulting to `denied`, so
gtag sends cookieless pings and sets no cookie. That is what makes the
published sentence "nothing is stored on your machine" true, and it is why the
site carries no consent banner. Google Signals is off in the property, so none
of this feeds advertising. [LAWYER] Confirm that cookieless Consent Mode is
sufficient to go without a banner in the jurisdictions the site is read from;
the mechanism is built either way, only the sentence depends on the answer.

The tag is gated on the hostname, so Vercel preview deployments and local
development do not report into the same property as the live site.

The calculators compute in the browser. Nothing typed into one is sent
anywhere: no request is made at all, and the pacing tool's pasted script in
particular never leaves the page.

The landing page also carries a review carousel from SaaS Browser, loaded from
`assets.saasbrowser.com`. The reviews are written on their site rather than
ours, and nothing flows from our page into it: there is no form behind it and
nobody signs in to it here. What it does mean is that a visitor's browser
fetches a file from a host that is not ours, and that request carries the IP
address and user agent any request carries. Their policy governs what they do
with it. It loads on the landing page only, not on the calculators or the
static pages. [LAWYER] Confirm whether they have to be named as a processor,
or whether describing the request is enough.

**Where the tag lives.** `web/src/components/Analytics.astro` for the nine
pages that render through `Base.astro`, and inline in `privacy.html`,
`terms.html` and `delete-account.html`, which own their own `<head>` and cannot
import it. `web/src/components/analytics.test.ts` globs `pages/*.html`, so a
static page added without the tag fails the suite on the day it is added. The review
widget lives in `web/src/pages/index.astro` and nowhere else.

---

## Things this policy deliberately does not say

Recorded here so the omissions are choices rather than oversights.

- **No claim about training.** See above.
- **No specific sub-processor list beyond the table.** Hosting and error
  reporting are not decided yet.
- **International transfer language — resolved 2026-08-27.** Read off the
  dashboards: Supabase `us-east-1`, Railway US East (Virginia), Cloudflare R2
  Eastern North America (ENAM). Everything is stored and processed in the
  United States, and `web/privacy.html` now says so plainly. [LAWYER] The
  published sentence states the fact; whether the audience's jurisdictions
  (GDPR etc.) need transfer-mechanism language on top of it is counsel's
  call, resting on the vendors' own DPAs.
- **The children's provision is published — resolved 2026-09-03.** The Play
  content rating came back "Rated for 3+", which is a statement about the
  *content* (nothing objectionable), not about who the app is directed at —
  that is the target-audience declaration, and no under-13 group was declared
  (the Families policy flow, which Play forces on any app targeting children,
  was never triggered). A 3+ content rating beside "not directed at children"
  is the ordinary combination for a professional tool, so `web/privacy.html`
  now carries: *"Flintroom is a professional rehearsal tool, is not directed
  at children, and does not knowingly collect personal information from
  anyone under 13."*

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
| Recording off means never accumulated | `backend/app/modules/voice/mixing.py` → `RoomMixer(keeping=False)` stores nothing; `router.py` reads the preference before the first frame |
| A line's offset is a number, not a copy of the audio | `backend/app/modules/sessions/models.py` → `TranscriptLine.began_at_seconds` |
| The disclosure precedes the microphone prompt | `app/src/lib/consent/entry.ts` |
| Coach conversations are stored with the room | `backend/app/modules/sessions/models.py` → `session_coach_turns`, `session_sparring_attempts` |
| A written panelist stays yours and dies with the account | `backend/app/modules/panels/models.py` → `CustomArchetype`; `docs/account-deletion.md` |
| Purchases carry no card details | `backend/app/modules/billing/` consumes RevenueCat webhooks only; no payment fields exist anywhere in the schema |
| The site sets no analytics cookie | `web/src/components/Analytics.astro` → Consent Mode default `analytics_storage: 'denied'`, asserted in `analytics.test.ts` |
| Every page carries the same tag, or none does | `web/src/components/analytics.test.ts` globs `pages/*.html` and compares the inline copies to the component |
| A calculator's inputs never leave the browser | `web/src/lib/*.ts` are pure functions; the site makes no request but the waitlist POST |

The full reasoning behind these decisions is in `docs/session-retention.md`.
