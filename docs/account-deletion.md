# Deleting an Account

**Status:** decided 2026-08-18, opening task #53. Taken with the human on the
same day, before any code.

Apple has required in-app account deletion since 2022 for any app that supports
account creation, so this is a store blocker rather than a courtesy. It also
blocks `docs/privacy-policy.md`, which currently claims a control that does not
exist.

> **Naming.** *Deletion* is the whole flow. *Anonymising* is what happens to
> records that survive it. *The window* is the seven days between a request and
> the purge.

---

## Problem

There is no endpoint and no flow. The Settings screen has the button and it
says "not yet built".

**The shape of the difficulty is a decision working as intended.** `user_id` is
a plain UUID and never a foreign key to `auth.users` (`CLAUDE.md` → Database
portability) — the single choice that separates a weekend migration from a
quarter-long one. The cost is that nothing cascades from a *user*, so every
table has to be named by hand. A table forgotten today is personal data retained
forever, with nothing raising.

What does cascade is content. Nine tables hang off `sessions` with
`ondelete="CASCADE"`, and `material_claims`, `voice_tickets` and `session_costs`
hang off their own parents. Deleting the parent rows takes the transcripts,
recordings, weak answers, coaching turns, sparring attempts, panelists, phase
spans and claims with them. The decisions below are only about what does *not*
cascade.

---

## Decisions

### 1. Money is anonymised, never destroyed

`accounts` and `ledger_entries` keep their rows, untouched, and the account is
marked deleted.

> **Corrected 2026-08-18, during implementation.** This first read *"`user_id`
> is replaced with a tombstone identifier"*, and that is both impossible and
> unnecessary. Impossible because `ledger_entries.user_id` is a foreign key to
> `accounts.user_id`, which is itself the primary key — there is nothing to
> repoint it at. Unnecessary because **`accounts` holds nothing identifying**:
> tier, period, and three balances. The only row that maps a `user_id` to a
> person is `auth_identities`, which carries the provider subject and the email.
>
> **So destroying `auth_identities` is the anonymisation.** Once it is gone the
> UUID maps to nobody and the account is a bucket of numbers. That is also
> strictly better than the tombstone would have been: a shared tombstone would
> have made every departed user's ledger indistinguishable from every other's,
> so a chargeback or a tax query about one purchase could never be answered
> again. Keeping the opaque key keeps that possible while keeping the person
> out of it.

Tax and accounting law generally requires financial records to outlive the
customer relationship, and `ledger_entries` is append-only by design —
`CLAUDE.md` calls it *the* money record and forbids mirroring it anywhere else.
Destroying it would leave RevenueCat holding purchases this side cannot account
for, and would leave the ledger's own reconciliation test reconciling against
gaps.

*Open, and it is a real one:* **the retention period is jurisdictional and needs
an answer before launch.** The mechanism does not wait on it — anonymised rows
can be dropped later on a schedule once somebody has decided what the schedule
is. `docs/privacy-policy.md` carries a `[CONFIRM]` on exactly this.

### 2. Cost telemetry is anonymised on the same terms

`session_costs` and `extraction_costs` are left exactly as they are, on the same
reasoning as the money: the `user_id` on them stops being personal data the
moment `auth_identities` is destroyed.

`tier` is already denormalised onto those rows precisely so that historical
analysis is not re-priced every time somebody upgrades. The same reasoning
extends to somebody leaving: the cost of a room in August is a fact about
August. Every price in `Product.md` §4.4 rests on these rows, #14 has not run
yet, and destroying them would put holes in the observed-cost history exactly
where the heaviest users were.

This is the decision most likely to be questioned in review, so the reasoning is
worth stating plainly: what is kept is *what a session cost us*, with no link to
who had it. That is a business record about our own spending, not a record about
a person.

### 3. The audit trail survives, because that is what it is for

`audit_events` is deliberately built with **no foreign keys** so that a row
outlives whatever it describes — `CLAUDE.md`: *"a record that disappears with
the account it indicts is not an audit trail."*

So it survives, and the deletion itself is recorded in it. What its rows may
still *contain* about a deleted user is bounded by the redaction that already
applies to every audit context; nothing new is written on the way out.

### 4. Seven days, then the purge

A deletion request marks the account and signs them out. A sweep purges after
seven days.

The window recovers the misclick, which matters on an account with real sessions
in it. It costs three things, each named here so none is discovered later:

- **A disclosure sentence.** For seven days "deleted" means "hidden", and
  `docs/privacy-policy.md` has to say so rather than imply immediacy.
- **A sweep that can stop running.** `docs/deployment.md` already treats sweep
  silence as an alertable condition for recordings, because audio outliving a
  published promise is invisible from inside. This is the same failure with a
  worse subject, and it needs the same alert.
- **A period where the data is alive.** The retention sweep, the reaper and
  every other background pass still see these rows. Nothing about the window may
  suspend them; a session that would have expired still expires.

### 5. Signing in cancels it, and the app says so

Signing in during the window calls the deletion off, and the user is told
plainly: *"Your account was scheduled for deletion. Signing in has cancelled
that."*

**The message is the load-bearing half.** An account that quietly un-deletes
itself is worse than one that stayed deleted, because the user would never learn
their data is still there. The cancellation is also an `audit_events` row: a
deletion reversed is exactly the kind of thing that has to be provable
afterwards.

---

## What must be true when it is built

Each of these is a property rather than a step, because the failure mode here is
silent.

- **Every table is named explicitly**, and a test enumerates them. Adding a
  table that carries `user_id` without adding it here must fail the suite rather
  than quietly retain data — the one guard that makes the plain-UUID decision
  safe rather than merely cheap.
- **Object storage is included.** Room recordings live in R2 and a row saying
  the audio is gone while the object is not is worse than either. Material
  source documents are already deleted on successful extraction
  (`docs/ingestion.md`), so the outstanding objects are recordings and anything
  a failed extraction left behind.
- **Idempotent.** Deleting twice is not an error, and the second request must
  not extend the window.
- **Authenticated and rate-limited**, like every other endpoint that costs
  something irreversible.
- **Audited.** The request, the cancellation and the purge are three separate
  `audit_events` rows, because they answer three different questions.
- **Tokens revoked at request time**, not at purge. Signing out is part of the
  request; leaving a refresh token alive for seven days would let a stolen one
  cancel the deletion.

---

## Built, 2026-08-18

All six properties above hold, and `docs/privacy-policy.md` no longer carries a
`[CONFIRM]` on this control. Where it lives: `billing/deletion.py`,
`DELETE /v1/me` in `auth/router.py`, the sixth sweep in `sessions/runner.py`,
and `lib/account/deletion.ts` on the phone.

Three things the build settled that the decisions above did not anticipate.

**The tombstone was impossible and unnecessary** — corrected in decision 1
above rather than quietly changed, because the replacement is better than the
original would have been if it had worked.

**A sweep with no object store refuses outright.** This is stricter than the
retention sweep, which is simply skipped, and the asymmetry is the point:
retention leaves a row carrying `deleted_at`, so a skipped pass stays visible,
while a purge destroys the only rows that know an object exists. There is no
backstop that can recover from that, so `DeletionSweepUnconfigured` is raised
before anything is destroyed.

**One account that cannot be erased must not jam the queue.** The purge is
all-or-nothing per account — a store that raises rolls the transaction back and
the rows survive alongside the objects — but the *sweep* catches per account
and carries on, so a permanently unhappy key stops one deletion rather than
every deletion in the system. `account_purge_failed` names the account; a
repeat of the same `user_id` is a deletion stuck inside its seven days.

**Still open:** the retention period for anonymised financial records, which is
jurisdictional and named in decision 1. Nothing is blocked on it — those rows
can be dropped on a schedule once somebody decides what the schedule is — but
`docs/privacy-policy.md` still carries a `[CONFIRM]` on that line and cannot be
published while it does.
