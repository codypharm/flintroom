# Onboarding

**Status:** decided 2026-08-12. Builds in Phase 5 (Week 8) per `Product.md` §7 —
this document exists so that build is not re-deciding any of it from memory.

`Product.md` §9 lists **onboarding length** under "Undecided, do not invent."
This document closes that item. Everything below is a resolved decision with the
reasoning that produced it; where something is still open it says so explicitly.

---

## Problem

A new install knows nothing. The product's entire value is visceral — being
interrogated about your own argument feels different from reading that you will
be — and none of that is conveyable on a screenshot. Meanwhile the v1 audience
(corporate/executive presenters, product managers, consultants, founders) is
skeptical, time-poor, and quick to read consumer-app theater as unseriousness.

So onboarding has to build enough investment to carry a stranger into their first
session, using questions rather than claims, without spending fifteen screens
doing it.

## Solution

A short first-launch survey whose questions **do real work** — every answer
changes something the user will see — ending in a reveal of the panel assembled
from their answers, then sign-in, then their first session on the free tier.

```
Launch ─► 5 questions ─► "Here's your room" ─► Sign in ─► First session (free 15 min)
                                                                    │
                                                     Paywall lands here, after the
                                                     complete first experience
```

**Onboarding's job is to get them into the room, not to get them to pay.**
`Product.md` §4.4 already grants 15 lifetime minutes — one complete session
including debrief and sparring — and states the reasoning: *"People convert after
feeling the value, not after sampling it."* The paywall is therefore downstream of
onboarding entirely, which makes onboarding's job easier and its story honest.

---

## The five questions

Five, because each has to justify its screen against an impatient professional,
and because these five are exactly what the product can act on. A question that
cannot change a default does not belong in the flow.

| # | Question | Configures |
| --- | --- | --- |
| 1 | What are you preparing for? | Use-case scope check + event type |
| 2 | When is it? | Return prompt; also a read on whether this is real |
| 3 | What's your role? | Default panel composition |
| 4 | Who's actually in that room? | Default panel composition, more sharply than role alone |
| 5 | How hard do you want them to go? | First-session difficulty |

Q4 earns its place separately from Q3 because role predicts the *user*, not the
audience. A product manager presenting to a steering committee and a product
manager presenting to engineering need different archetypes, and only Q4
distinguishes them.

Q5 is doing double duty. It sets the difficulty starting point, and it is the
clearest positioning statement in the flow — no delivery-metrics scorer has ever
asked how much heat you want.

### The reveal

After Q5: **"Here's your room."** The archetypes selected from their answers,
named, each showing the angle it will come at them from.

This is the payoff, and it only works because the survey configures for real. A
reveal backed by a survey that changed nothing is a promise the first session
immediately contradicts — and this audience checks.

---

## Decisions

### The survey configures the product, it is not analytics theater

Considered and rejected: collect answers for segmentation only, decoupled from
the panel work. Cheaper and faster, but it makes the reveal a lie that the first
session exposes within a minute. Skeptical professionals notice, and the moment
they notice is the moment the wedge stops being credible.

### Survey first, sign-in after

Identity is asked for once there is something to lose. The account becomes the
way to keep the room they just watched get built, rather than a toll gate in
front of a stranger.

Answers are held on-device through the survey and posted at sign-up. This keeps
the backend simple and preserves a rule from `CLAUDE.md`: `user_id` exists only
for a real user. No anonymous account records, no orphan rows per bounced
install, no merge path, and nothing that drifts toward device-coupled identity.

The cost is honest and accepted: **no per-question drop-off analytics** for users
who abandon before sign-up, and no resume across a reinstall. If drop-off inside
the survey later needs measuring, that is a client-side analytics event carrying
no `user_id` — not a server-side anonymous account.

### Mic permission at first session start, never at launch

An iOS microphone denial is sticky. Once refused, the app cannot re-prompt and
the user must find the toggle in Settings — which, for a voice-only product, is a
dead install. So the prompt appears at the moment its reason is self-evident:
they have tapped to enter the room and the panel is waiting.

This also follows Apple HIG, which matters against Open Risk #5 — a mic-access AI
app draws review scrutiny, and asking for the microphone before showing anything
is the pattern reviewers look for.

**The permission is settled before the session is minted**, not after. `POST
/v1/sessions` creates a session row and a stream ticket, and the ticket expires
in seconds — so minting first and asking second leaves a user who taps "don't
allow" holding a dead ticket against a live session, and the room they cannot
speak in has to be reaped rather than simply never created. `ensureMicrophone`
(`app/src/lib/audio/permission.ts`) returns the outcome that decides this, and
the caller entering the room is where the ordering is enforced.

**A refusal is never re-prompted.** The platform reports `Denied` without saying
whether asking again would show anything, and on iOS it never will — the call
resolves `Denied` immediately, with no dialog. So a refusal routes to our own
explanation and a deep link into Settings, identically on both platforms. A
retry button that silently does nothing reads as a broken app rather than as a
setting the user controls, and Android gains little from the branch: a second
denial there is equally permanent.

A permission call that *throws* is reported separately from a refusal
(`unavailable`). It is our failure, not the user's, and sending them to Settings
to fix a permission they never refused — where they would find it already
granted — is how an app teaches someone not to trust what it says.

### Sign in with Apple + Google

Two taps, no password storage, no reset flow, both platforms covered. The
constraint is a store rule, not a preference: offering Google makes Sign in with
Apple mandatory on iOS. They ship together.

Email links were considered for the corporate user who will not attach a personal
Google account to a work tool. Deferred rather than declined — it is additive
later, and it sits at exactly the moment the flow has spent five screens building
momentum, where a mail round-trip is the worst possible interruption.

**Forward constraint:** `Product.md` §4.4 has a Teams tier at a 10-seat minimum.
Organizations buying seats will want SSO. The auth interface must accept an OIDC
provider without restructuring — free to preserve now, expensive to retrofit, and
the same reasoning as the voice-provider interface.

### Streaks: rejected

Considered at the same time as the rest of this, and declined.

- **They punish the usage pattern the product serves.** `CLAUDE.md` locks the
  allowance unit as monthly rather than weekly for exactly this reason:
  *"Rehearsal is bursty; weekly reset punishes exactly the usage pattern the
  product serves."* A daily streak is that same mistake on a harsher clock. The
  best user prepares hard for four days before a board review and then does not
  open the app for three weeks. A streak tells that person they failed.
- **They cost real money.** A streak's function is to make people open the app
  with no reason to. Here that means starting a metered interrogation — genuine
  provider cost, against Open Risk #4, for a session nobody needed.
- **Wrong genre.** `CLAUDE.md`: *"do not let the product drift toward a
  delivery-metrics scorer or a companion/social app."* Streaks are companion-app
  furniture.

**Replaced by the event countdown.** Q2 captures the real event and its date, so
the product can return with *"Board review in 6 days"* — urgency drawn from the
user's actual stakes rather than our engagement metrics, rewarding the burst
instead of punishing it.

**Reopen if:** post-launch data shows a substantial cohort rehearsing on a
genuinely regular cadence (weekly standing meetings, teaching, recurring reviews)
rather than around discrete events. That is a different usage shape, and a
recurrence mechanic aimed at it would not carry the objections above.

---

## Backend implications

None of this is built yet. Recorded here so the work lands in the right phase.

- **The free grant is a ledger concern, not an onboarding one.** Completing
  onboarding triggers a 15-minute grant that is *lifetime, never resetting* —
  distinct from the monthly allowance, and therefore its own `EntryReason` and
  its own bucket semantics at the period boundary. This belongs with the
  entitlement work in Phase 1, ahead of any onboarding UI.
- **Survey answers post once, at sign-up**, as part of account creation rather
  than as a separate call — a partially-created account with no configuration is
  a state worth not having.
- **Panel defaults and difficulty are read from those answers**, which means
  onboarding depends on the panel composition and difficulty calibration work in
  Phase 3. It is scheduled after them; do not invert that.
- **Archetype selection stays configuration, not code**, per the locked
  architecture decision. Survey answers map to archetype sets through config.

## Testing decisions

Written when this is built, not now — but the shape is set by what would actually
break in production:

- **The free grant is granted exactly once per user, ever.** The failure that
  matters is a user re-running onboarding, or a retried sign-up, minting a second
  15 minutes. Idempotency on the grant, tested the way the ledger's other
  idempotency is tested.
- **A user who abandons before sign-up leaves nothing behind.** No account, no
  ledger row, no partially-configured record.
- **Survey answers reach panel composition.** The reveal has to match the room —
  an assertion on the archetypes selected for a given answer set, not on the UI.
- **The deferred use cases are actually caught** by Q1 and routed to an honest
  "not yet" rather than a session.

## Out of scope

- **Copy and story beats.** The words on each screen are design work and are not
  decided here. The structure above constrains them; it does not write them.
- **The deckless grounding problem.** `Product.md` §3.2 makes material optional —
  *"Voice is the primary input"* — so a user with no slides is a supported and
  common path. But the Auditor's job is cross-checking transcript against
  material, and with no material there is nothing to check against, which runs
  straight into Open Risk #2. This is a real product problem and it belongs to
  the Auditor work, not to onboarding. It needs its own decision.
- **Teams onboarding.** Seat invitation and org-level setup are a different flow
  for a different buyer.
- **Re-onboarding.** What an existing user sees when their event passes, or when
  they return after a long absence, is a retention question and not this one.
