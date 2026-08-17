# What a Saved Session Retains

**Status:** decided 2026-08-17, closing task #29. Builds across the end of Phase 3
and the start of Phase 4 per `Product.md` §7 — transcript persistence is a
prerequisite for the debrief, and the audio path is not.

Resolves what survives an interrogation, for how long, and who is allowed to hear
it. `Product.md` §413 lists the recording-retention window under *"Undecided, do
not invent"*; this document is that decision, taken with the human on
2026-08-17.

> **Naming.** A *room* is one interrogation. The *transcript* is its text, both
> sides. The *recording* is the mixed audio artefact defined below. *Auditor* is
> the domain agent, never the `audit_log` module — and nothing here is an audit
> record in that sense.

---

## Problem

Nothing persists. `OrchestratedChannel._transcript` says so in its own docstring
— it holds the room *"for the life of the room and nothing beyond it"* — and
`relay.py:240` forwards each `AgentTranscript` to the phone and drops it. There
is no model, table or column for either transcript or audio.

Two things depend on that changing, and they are not the same thing.

**The debrief cannot be built.** `Product.md` §405 scopes the coach to *"that
session's artifacts — transcript, ranked weak answers, Auditor findings, and
ingested material"*, and `CLAUDE.md` requires that scope be structural rather
than a system prompt, because a prompt saying "don't do general pitch review" is
one jailbreak from handing every user unlimited free pitch review. A coach that
cannot see the transcript has no grounding to be constrained *to*. This blocks
Phase 4 entirely.

**The human intends sessions to be replayable.** Stated 2026-08-15 and reaffirmed
2026-08-16 and again 2026-08-17: sessions are saved so users can come back and
play them, hearing both their own voice and the panel's.

The second is where the exposure is. `Product.md` §1 says Flintroom is *"not a
recording utility"*, §3.4 deferred video partly on sensitive-recording-storage
grounds, and Open Risk #5 is that mic-access AI apps draw store scrutiny.

---

## Decisions

### The transcript has two lifetimes, not one

It is always written, and always survives interrogation → debrief → sparring on
every tier including Free. That is a functional requirement, not a feature: it is
what the coach is grounded in.

How long it survives *after* settlement is a separate question, answered below.
Splitting them is what lets `Product.md` §4.4 keep selling "full session history"
as a Pro differentiator without the free tier's debrief silently depending on an
entitlement — and `CLAUDE.md` forbids a paywall appearing anywhere near a live
session.

### The recording is the full room, both voices

Decided by the human against the recommendation recorded here, and the
disagreement is worth preserving because the argument will recur.

**The case against**, which was put and overruled: hearing your own voice back is
how you notice hedging, pace and filler — which is *delivery*, precisely what
`Product.md` §1 says competitors sell and Flintroom refuses. Retained user audio
quietly equips the product to become the thing the wedge exists to reject.

**The decision**: full room, both voices, replayable. The counter-argument is
that replay is a rehearsal artefact rather than a scoring one — nothing measures
or grades the audio, and the substance attack still lives entirely in the panel
and the Auditor. The wedge is defended by what the product *does with* a room,
not by refusing to let a user hear it.

This is the human's call under `CLAUDE.md` — product decisions are, and this one
also sets the privacy posture.

### Playback plays the stored file. It never re-synthesises

Re-rendering the panel from the transcript was considered and is dead on two
counts.

It is *more expensive than storing*, by about two orders of magnitude.
`docs/voice-cost.md` measures panel speech at ~$0.04 per interrogation minute and
~88% of a room's entire bill, so re-synthesising a twelve-minute room costs
roughly **$0.48 every press of play**, against a fraction of a cent per month to
keep it. Nothing else in this product has that ratio.

It is also *impossible for half the artefact*. A synthesis vendor can regenerate
the panelists. It cannot regenerate the user's voice at any price. Once the room
includes both sides, storage is the only mechanism.

Consequence worth stating plainly, because it is the first question anyone asks:
**playback consumes no ElevenLabs credits.** It costs egress and nothing else.

### One mixed track, positioned where it was heard

The stored artefact is a single Opus object: the user's continuous uplink, with
panel speech mixed in at the position it actually played, truncated wherever
barge-in cut a panelist off.

Two facts make this the right shape:

**The user's uplink is continuous.** `app/src/lib/audio/uplink.ts` converts and
sends every frame the recorder produces, with no voice-activity gating anywhere
in the client. So the user stream is an unbroken 16 kHz timeline for the life of
the room — a free wall clock to position everything else against.

**Panel audio is not.** `relay.py:250` records that frames run ahead of playback,
which is why barge-in has to call `discard_playback()`. Panel frames therefore
arrive in bursts, and some of them are **never heard**. Appending them naively
produces a recording in which a panelist cut off at two words keeps talking for
another eight seconds — every barge-in replaying as a lie, about the one moment
the product is built around.

So the mixer is fed by three things the relay already has: user PCM, panel PCM,
and `Interrupted`. What is written is what was heard.

Rejected: two aligned tracks (playback drifts when two players are synchronised
on a phone, and the only thing it buys — erasing the user's half while keeping
the room — is not a legal requirement, since deleting the object satisfies
erasure outright); and user-track-plus-panel-clips (elegant, gives per-question
seek for free, but ~16 objects per room and playback becomes clip scheduling
against a clock rather than pressing play). The clip model is the natural v2 if
"jump to the margin question" is ever wanted in the debrief.

### Mixing needs no dependency. Encoding needs one

`audioop` was removed from the standard library in Python 3.13 (PEP 594) and this
backend runs 3.14, so the obvious helper is gone. It turns out not to matter.

Mixing PCM16 is addition with clipping, and done incrementally per arriving frame
rather than in a bulk pass, it is free. Measured, worst case — the panel speaking
for the entire twelve-minute cap:

```
36,000 frames    total 1.39s    per frame 0.039 ms
                                budget    20 ms
```

Five hundred times the headroom, spread across twelve minutes, off the hot path.
Pure stdlib `array`. No numpy.

That leaves exactly one job needing a dependency: Opus encoding and Ogg
containerisation. **PyAV**, chosen because its wheels bundle ffmpeg and libopus —
no system binary to install, version or debug. That is the same reason
`pyproject.toml` already gives for choosing `pypdfium2` over `pypdf` plus a
poppler subprocess, so it is house precedent rather than a fresh argument. An
ffmpeg subprocess was the alternative and was rejected on the failure it hides:
whether libopus is compiled into the binary varies by base image, and you find
out in production rather than at install.

### The room accumulates in memory and is written once, at settlement

`SESSION_LIMIT` is **12 minutes**, which bounds a live room at ~23 MB of mixed
PCM16 — roughly 1.2 GB at fifty concurrent rooms. That cap is already enforced,
so it is a real bound rather than a projection. (The figure in task #29 assumed a
twenty-minute session and is superseded.)

At settlement the buffer is encoded to Opus in a worker thread and written with a
single `ObjectStorage.put` — the interface that already exists, unchanged. No
multipart, no incremental encoder state, no widening of a contract every storage
backend has to implement.

The cost is honest: a process death or a mid-room deploy loses that room's audio.
Incremental multipart upload is the only thing that fixes it, and it is not worth
widening the storage interface for a failure window a twelve-minute cap already
keeps small.

**Encoding cannot happen where capture happens.** `relay.py:258` prohibits codec
work in the relay's audio path — *"re-encoding here would put decode latency into
the path the ~1.5s illusion threshold is measured across"* — and that prohibition
stands. Capture taps the two chokepoints; encoding happens once, later, elsewhere.

### It is done server-side, and that is not incidental

The phone is the only party that knows exactly what it played, which makes
client-side capture superficially attractive. It is refused on two grounds:
`CLAUDE.md` forbids mobile-only assumptions so that a web client stays possible
without a backend rewrite, and it would mean trusting a client to upload the
user's own voice. The server can reconstruct what was heard from `Interrupted`,
which is the same answer without either cost.

### A failed room keeps nothing

Audio is written on the **settle** path only, never the fail path.

`CLAUDE.md` refunds minutes automatically on technical failure. A refunded
session is one the product has declared did not happen, and retaining its audio
contradicts that — so a room that dies mid-interrogation is discarded even though
the mixer is still holding it.

This turns out to need no special case. The reaper runs in a different process
from the relay, so an abandoned room's buffer is already gone by the time
anything could flush it, and abandoned rooms are refunded too. Normal ends keep
the room; failures and abandonments do not. One rule.

### Saving is on by default, disclosed at first session start

A one-time sheet at the moment mic permission is settled — which
`docs/onboarding.md` already argues is when the ask is true and actionable.
It states that rooms are saved so they can be played back, how long they are
kept, and that any room can be deleted, or saving turned off, in Settings.

OS microphone permission means *"we may hear you"*, not *"we keep it"*. Those are
different asks and stores treat them differently. What stores require for a
recording the user is themselves making is disclosure and control, not opt-in.

Opt-in was rejected on the grounds that most users never open Settings, which
would build a compounding cost centre the majority never switch on — and leave
"come back and play it" quietly broken for almost everyone.

One thing that makes this simpler than it looks: a room is one person talking to
synthetic voices. There is no second human whose consent is at issue, so this is
disclosure and control rather than two-party consent. A colleague sitting in is
the exception, and is not designed for.

### Retention: text outlives audio

| | Transcript | Audio |
| --- | --- | --- |
| Free | life of account | **30 days** |
| Starter | life of account | **90 days** |
| Pro | life of account | **12 months** |

The windows live in `billing/tiers.py` beside `MONTHLY_ALLOWANCE_SECONDS` and
`MAX_UPLOAD_BYTES`, which is where `docs/ingestion.md` already puts per-tier
figures that are pricing.

**Text and audio are split because only one of them compounds.** A transcript is
tens of KB and effectively free forever; §4.4's "full session history" stays
literally true on every tier. Audio accrues monthly, grows with every session
ever run, and keeps being charged for a user who churned — so the window binds
where the cost actually is.

The numbers were derived rather than picked. Opus at 24 kbps is ~180 KB per
interrogation minute, and R2 storage is ~$0.015/GB/month:

| Tier | Interrogation/mo | Audio/mo | Steady state | At 10k users |
| --- | --- | --- | --- | --- |
| Free | 15 min **lifetime** | 2.7 MB *total, ever* | 2.7 MB | ~$0.40/mo |
| Starter | 90 min | 16.2 MB | 49 MB @ 90d | ~$7/mo |
| Pro | 3 hours | 32.4 MB | 389 MB @ 12mo | ~$58/mo |

**The Free window is worth nothing in cost terms, and an earlier proposal of 7
days was withdrawn because of it.** A free user is capped at 15 minutes for life,
generates 2.7 MB, and then stops forever — even 100,000 free accounts retained
indefinitely is around $4/month. A short free window saves nothing measurable
while deleting the single artefact §4.4 says has to sell the subscription.

Pro is the only tier where retention compounds, because it is the only one
generating tens of megabytes every month indefinitely. Twelve months is what
makes "full session history" mean something without becoming an unbounded
promise, and a bounded number is a clean sentence for the privacy policy.

### Cloudflare R2, because playback is pure egress

`docs/deferred-scale-work.md` deferred the production object-storage vendor and
named this task as the trigger. It has fired.

Every press of play is egress and nothing else, and R2 charges none. Two of the
decisions above also shrink the projection in that document: `SESSION_LIMIT` is
12 minutes rather than the 20 it assumed, and split windows put most rooms on 30
or 90 days.

The exit stays four environment variables plus `S3_ADDRESSING_STYLE`, because
nothing above `core/storage_s3.py` holds a vendor SDK. That is what makes this
decision cheap to take and cheap to reverse.

Its own caveat, from that document, is now live: R2's compatibility thins around
lifecycle rules, and a lifecycle rule is exactly what the next decision uses as a
backstop. Check it against R2's list rather than assuming.

### The sweep enforces the window; a lifecycle rule sits underneath it

A periodic job — the same shape as the session reaper and ingestion's retry sweep
— finds rooms past their owner's **current** tier window, deletes the object, and
writes an `audit_events` row. Beneath it, a deliberately generous R2 lifecycle
rule (Pro's window plus a margin) guarantees that a dead sweep cannot retain data
indefinitely.

Lifecycle rules alone are the industry default for undifferentiated bulk data —
logs, backups, caches — where one bucket shares one policy. This data is not
that. It is per-user, per-tier, mutable on downgrade, and covered by a published
promise, which puts it in the category where application-enforced deletion is
standard:

- An erasure request needs a completion record. A bucket policy is a
  *configuration*, not evidence that one user's data is gone.
- Auditors ask you to demonstrate deletion occurred, not that the bucket was set
  up correctly.
- **Tier changes are the decisive case.** A Pro user with twelve-month rooms who
  downgrades to Free needs every existing object re-tagged or moved for a
  lifecycle rule to be correct. A sweep reading the tier at sweep time is simply
  right.

The two-layer shape mirrors how `CLAUDE.md` already reasons about RLS:
service-role access through the API is the real wall, and RLS is defense-in-depth
behind it. The enforcing layer owns the policy and the proof; the backstop must
never become load-bearing.

`docs/deployment.md` already lists sweep silence as needing alerting. This is the
sweep where silence is a privacy incident rather than a bug.

### Delivery is a presigned GET at the existing expiry

The service checks ownership and entitlement, then returns a presigned URL,
exactly as ingestion does for thumbnails. No proxying, no new constant, no
widening of `presign_get`.

`DEFAULT_EXPIRY_SECONDS` is 15 minutes, which looked too short for a 12-minute
recording until the arithmetic: the object is ~2.2 MB, so the phone downloads it
in seconds and plays from a local buffer. **The URL has to outlive the fetch, not
the listen**, and seeking happens against bytes already on the device.

A longer expiry was rejected as widening an interface for a problem 2.2 MB does
not have, on the most sensitive object in the system. An authenticated streaming
endpoint was rejected because it puts every replay through a worker and turns
egress into API load — the opposite of why R2 was chosen.

---

## Deliberately not decided

**Billing on retained storage.** Raised by the human on 2026-08-16 and explicitly
not decided then or now. It would add a second metered axis beside Time Under
Fire, which is a pricing change — human's call, and blocked behind the §4.3
cost-instrumentation task like every other price in this product.

**Per-question seek.** The clip-per-utterance storage model would give it for
free and was rejected for v1 on playback complexity. Reopen it if the debrief
wants to jump to a specific challenge.

**Incremental upload.** Reopen if mid-room deploys become frequent enough that
losing a room to one is a real complaint rather than a theoretical one.

---

## Build order

Transcript persistence stands alone and unblocks Phase 4. Everything else is the
audio path and blocks nothing.

1. **Transcript persistence** — the model, the write on each line through the
   same relay chokepoints that already write `record_speech` and `Spent`, and
   life-of-account retention. Unblocks the debrief.
2. **The mixer** — heard-position placement and barge-in truncation, tested
   against `Interrupted` without any encoder in the loop. This is where the
   correctness risk is.
3. **Encode and store** — PyAV at settlement, single `put`, discarded on the
   fail path.
4. **The retention sweep** — per-tier windows read at sweep time, `audit_events`
   on every deletion, plus the R2 lifecycle backstop.
5. **Playback** — entitlement check, presigned GET, and the contract change.
6. **Consent and controls** — the first-session disclosure sheet, the Settings
   toggle, and per-room delete.
