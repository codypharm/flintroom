# Setting up billing: Play, RevenueCat, and Apple later

**Status:** setup guide, not a decision record. The decisions are `Product.md` §4.4–4.5
and `docs/minutes-ledger-and-sessions.md`; this is the sequence of dashboard work
that turns them into products a phone can buy.

**The deliverable** is a list of store product identifiers and entitlement
identifiers, which is what `billing/tiers.py` maps to tiers. Nothing generates
them — they are strings you choose, typed into a store console, and mirrored by
RevenueCat.

**None of this is needed yet.** The backend billing path — webhook verification,
entitlements, grants, the ledger — is built and tested against synthesised events
with no store account of any kind. What an account buys is proof against a real
event and the ability to ship, and neither is on the critical path until there is
somebody to ship to. Pay when a trigger below is actually met, not in advance.

| Cost | What it unlocks | Pay when |
| --- | --- | --- |
| **$0** | Everything in this repo: the webhook, the ledger, the panel work, the client against a dev build | — |
| **RevenueCat, $0** | Free below a monthly-tracked-revenue threshold well past first revenue. Verify the current threshold rather than trusting this line | — |
| **Play, $25 once** | A real purchase, a real webhook, an Android tester who is not you | You want to confirm the identifiers against a live event, or put the app in somebody else's hands |
| **Apple, $99/year** | TestFlight, an iOS release, Sign in with Apple on a real build | iOS is being shipped. Not before |

**The costs that are not optional are the per-use ones**, and they are the ones
worth watching: the extraction model, and the voice provider at an assumed
~$0.12/min that `Product.md` §4.3 says is unverified. Those are Open Risk #4, and
a store fee is noise beside them.

Do it in the order below. Two steps have multi-day latency and block everything
after them, and both are administrative rather than technical.

**Google goes first, decided 2026-08-16.** Play registration is $25 once against
Apple's $99 a year, and the backend is store-agnostic — the webhook, the ledger
and the tier mapping do not know or care which store an event came from. So the
whole billing path can be proven on Android and Apple added later at no rework.

This does **not** reopen the iOS-led platform decision in `CLAUDE.md` §9. That is
about design language and interaction, and it is unaffected by which store gets
wired first.

---

## 0. The long poles, started first

Neither of these is work. Both are waiting, and everything else waits on them.

### Google — register the right *kind* of account

Play Console registration is a one-off $25. The choice made at signup is the one
that matters later:

**A personal account carries a testing requirement that an organisation account
does not.** Personal developer accounts registered since late 2023 must run a
closed test with at least 12 testers opted in continuously for 14 days before
production access can even be applied for. That is a two-week floor on shipping,
and it starts only once there is something to test.

If Flintroom is going to be a company, register as an organisation. It needs a
D-U-N-S number, which is free but takes days to issue, and that is the trade: a
few days now against a fortnight later, plus not having to migrate an account
whose name is on the store listing.

**Decided 2026-08-21: individual, not organisation.** Flintroom is a personal
project that may become a company later, and a D-U-N-S number presupposes a
registered business — so the organisation path is not deferred paperwork, it is
incorporating, which is a larger decision than a store account should force.

So **the fourteen-day closed test is on the launch path**, and the point of
writing it here is that it should be planned rather than discovered. Twelve
testers, opted in *continuously*, for fourteen days, before production access can
even be applied for — and the clock starts only once there is something worth
testing. `Product.md` §7 puts store submission in Week 8 with "a week of slack";
this does not fit inside that week, it runs alongside the ones before it.

Revisit if Flintroom incorporates before launch. Google supports moving apps
between developer accounts, so this is reversible at a cost rather than a
one-way door — but the fourteen days are not recovered by switching late.

### Google — a release on a track

Play Console will not show the Monetise section until the app exists and at least
one build has been uploaded to a track. Internal testing is enough; it needs no
review and no public listing. If the Expo app is not yet producing an AAB, this
is the thing to start early — it gates every product in §2.

### Apple — deferred, and what that costs

The Apple Developer Program is $99/year and nothing below needs it yet. Two
things wait on it, and neither blocks the billing work:

- **Sign in with Apple on a real build.** The backend already verifies both
  providers and the client already implements both, so Google sign-in carries the
  whole flow in the meantime. Apple's own review rules will require Sign in with
  Apple before an iOS release, not before now.
- **iOS device and TestFlight builds.** The simulator needs no account, and a
  free Apple ID will run a build on a physical device on a seven-day provisioning
  profile. Neither produces a purchase.

When it is taken, the long pole there is the **Paid Applications Agreement** —
App Store Connect → Business. Agreement accepted, bank account attached, tax
forms completed. **In-app purchases do not function until it is active**,
including in sandbox, and the failure is confusing: the product is simply not
returned to the app, exactly as though the identifier were wrong.

---

## 1. Decide the identifiers once

**Neither store lets an identifier be reused after it is deleted**, and Apple's
cannot be renamed at all. Pick the scheme once, and pick it now rather than when
Apple is added — the same strings should exist on both stores, because a mapping
keyed on one set of names and patched for the other is where a tier goes wrong.

Play's own rules: lowercase letters, digits, underscores and periods; must start
with a letter or digit.

The seven products `Product.md` §4.4–4.5 specifies:

| Plan | Kind | Identifier | Play base plan |
| --- | --- | --- | --- |
| Starter, $29/mo | Subscription | `flintroom_starter_monthly` | `monthly` |
| Pro, $59/mo | Subscription | `flintroom_pro_monthly` | `monthly` |
| Pro Annual, $599/yr | Subscription | `flintroom_pro_annual` | `annual` |
| Teams, $25/seat/mo | Subscription | `flintroom_teams_monthly` | `monthly` |

**Teams is not created in any store (decided 2026-08-25).** A per-seat plan
with a ten-seat minimum is a sale to an L&D manager or program lead, not a
phone paywall purchase — there is no seat management to sell through an app.
The row stays because the ID is reserved; the backend's `teams` tier in
`tiers.py` sits unused until an entitlement ever carries it, and adding it
later is console work with no app release.
| Quick top-up, $9 / 20 min | **Consumable** | `flintroom_topup_20` | — |
| Demo-day pack, $35 / 90 min | **Consumable** | `flintroom_topup_90` | — |
| Cohort block, $99 / 300 min | **Consumable** | `flintroom_topup_300` | — |

**Consumable, not non-consumable, for the three packs.** §4.5 says top-up minutes
never expire and the same pack is bought repeatedly. A non-consumable can be
bought once per account and is restorable forever, which is the opposite of both.

**Teams is a placeholder here.** Per-seat billing with a ten-seat minimum is not
an ordinary store subscription on either platform, and §4.4's Teams tier probably sells through
a different channel entirely. Create the other six and leave Teams until there is
a buyer; `docs/ingestion.md` and the ledger already treat it as a tier, so nothing
breaks by deferring the product.

---

## 2. Google Play Console — the one to do first

Do this after §0's release is uploaded, or the Monetise menus will not appear.

### 2.1 Subscriptions

Monetise with Play → Products → **Subscriptions**. Play's model has two levels
and the distinction matters to us:

- A **subscription** carries the product ID — `flintroom_pro_monthly`.
- A **base plan** under it carries the billing period, price and renewal type.
  One auto-renewing base plan per subscription is all this product needs.

Base plan IDs are lowercase, hyphens and digits only — `monthly`, `annual`. Give
them the same name across subscriptions so the pattern is boring.

**Activate the base plan.** A subscription with an inactive base plan is invisible
to the app and to RevenueCat, and looks exactly like a wrong identifier.

Play has **no subscription-group concept**. Apple's grouping is what makes Starter
and Pro mutually exclusive; on Play, upgrade and downgrade are the client's job,
declared at purchase time through the SDK's replacement mode. Nothing about that
reaches the backend — the ledger sees a `PRODUCT_CHANGE` event and the tier on it
— but it is a real difference in the paywall work.

### 2.2 The three top-ups

Products → **In-app products** → managed products, one per pack. Play calls them
managed products rather than consumables; what makes one consumable is that it is
*consumed* after purchase, which the RevenueCat SDK does. Without consumption the
same pack cannot be bought twice, so this is worth verifying against the second
purchase rather than the first.

### 2.3 Licence testers

Play Console → Settings → **Licence testing**. Add the tester email addresses;
they can buy every product without being charged, and the purchases are real
enough to fire webhooks.

Test purchases arrive with `environment: SANDBOX` — see the open question at the
foot of this document about whether those may grant real minutes.

### 2.4 The identifier Play reports may not be the one you typed

With base plans, a purchase can be reported as `subscription_id:base_plan_id`
rather than the bare subscription id. Since Play is the first store wired, this
is the ordinary case here rather than an edge case — do not guess at it, read it
off a real event per §5.

---

## 3. App Store Connect — deferred until the account exists

### 3.1 Subscription group

App Store Connect → your app → **Subscriptions** → create **one** group, e.g.
`Flintroom Plans`.

**Starter, Pro and Pro Annual all go in the same group.** Subscriptions within a
group are mutually exclusive, and Apple handles upgrade, downgrade and proration
between them automatically. In separate groups a user can hold two at once and be
charged twice, which is a support ticket and a refund rather than an upgrade.

The group's display name is user-visible in the subscription management screen.

### 3.2 Each subscription

Per subscription, Apple wants:

- **Reference Name** — internal only, never shown.
- **Product ID** — from the table above. Permanent.
- **Subscription Duration** — 1 month, or 1 year for Pro Annual.
- **Price** — chosen per territory; start with your base territory and let Apple
  generate the rest, then check the ones you care about.
- **Localization** — display name and description, at least one language. Shown
  on the App Store and in the system purchase sheet.
- **Review screenshot and notes** — a screenshot of the paywall showing the
  product. Reviewers reject purchases they cannot see in the app.

Set the **subscription ranking** within the group: higher rank means an upgrade.
Pro above Starter, and Pro Annual is a sideways move from Pro rather than a rung.

### 3.3 The three consumables

In-App Purchases → **Consumable**. Same fields, no group, no duration.

### 3.4 Sandbox testers

Users and Access → **Sandbox** → Test Accounts. Use an email address that is not
an Apple ID already. On the device, sign in under Settings → App Store → Sandbox
Account, **not** the main Apple ID.

A sandbox subscription renews on an accelerated clock — a month is minutes — which
is exactly what is needed to see `RENEWAL` and `EXPIRATION` events without waiting.

### 3.5 Before you have any of this

Xcode's **StoreKit configuration file** fakes products locally with no App Store
Connect involvement at all. Useful for building the paywall UI early, and it
produces no webhooks — so it proves nothing about the backend.

---

## 4. RevenueCat

### 4.1 Project and apps

Create a project, then add an app per platform. Android alone is enough to prove
the whole path; the iOS app is added later without changing anything below it.

- **Android** needs the package name and a **Google Cloud service account** with
  access to the Play Developer API, invited into Play Console and granted
  financial-data permission. This is the fiddliest step on either platform —
  three consoles, and propagation that can take up to 36 hours before RevenueCat
  stops reporting a credentials error. Follow RevenueCat's own guide rather than
  reconstructing it.
- **iOS**, when it exists, needs the bundle identifier and an **In-App Purchase
  Key** (App Store Connect → Users and Access → Integrations). Also point **App
  Store Server Notifications** at RevenueCat, so refunds and billing failures
  arrive without a poll.

### 4.2 Entitlements

Create entitlements — the thing the app checks, as opposed to the thing the user
bought. Suggested:

- `pro` → attach `flintroom_pro_monthly` and `flintroom_pro_annual`
- `starter` → attach `flintroom_starter_monthly`

Top-ups get **no entitlement**. They are consumables that grant a balance, not
access, and our ledger owns that balance — see §4.5's "top-up minutes never
expire", which is a fact about our database and not about a store subscription.

**Why our backend maps on `product_id` rather than entitlement.** Pro and Pro
Annual share the `pro` entitlement but are different tiers to us: the same monthly
minutes, different revenue, and §4.4 gives them different margins. Entitlement is
too coarse to decide what to grant.

### 4.3 Offerings

Configured 2026-08-26, and the identifiers are now load-bearing: the app's
adapter (`app/src/lib/billing/revenuecat.ts`) looks packages up by them, so the
console and that file must agree or the shop half-closes.

One offering, identifier **`default`**, six **custom** packages — the built-in
package types (`$rc_monthly`, `$rc_annual`) are unused because each is only
usable once per offering and we sell three different monthlies:

| Package identifier | Product | The app joins it to |
| --- | --- | --- |
| `starter_monthly` | `flintroom_starter_monthly` | rung `starter` |
| `pro_monthly` | `flintroom_pro_monthly` | rung `pro` |
| `pro_annual` | `flintroom_pro_annual` | `pro_annual` — off the ladder, renders nowhere yet |
| `topup_20` | `flintroom_topup_20` | pack `topup_20` |
| `topup_90` | `flintroom_topup_90` | pack `topup_90` |
| `topup_300` | `flintroom_topup_300` | pack `topup_300` |

Teams is absent — see §2's note. Display names and descriptions on packages
are dashboard-only text; only the identifier column above is contractual.

### 4.4 The webhook

RevenueCat → Integrations → **Webhooks**.

- URL: `https://<host>/v1/webhooks/revenuecat`
- **Enable HMAC signing** and copy the signing secret into
  `REVENUECAT_WEBHOOK_SECRET`. Do not use the plain Authorization-header option —
  a static header is replayable forever, and the HMAC covers a timestamp. See
  `docs/deployment.md`.
- Send a **test event** first. It proves the wall before money is involved, and it
  is the request that tells you the secret is wrong.

---

## 5. Read the identifiers off a real event

The mapping in `billing/tiers.py` should be written against what RevenueCat
actually sends, not against what was typed into a dashboard — Play in particular
may append a base-plan suffix nobody chose.

Every event currently lands on the ignored path and logs what is needed:

```
webhook_event_ignored provider=revenuecat event_type=INITIAL_PURCHASE
  event_id=... product_id=... entitlement_ids=[...] environment=SANDBOX
```

Make one sandbox purchase per product and collect `product_id` for each. Those
seven strings are the deliverable.

---

## Open

- **Teams is not a product yet.** Deferred in §1 above; per-seat with a ten-seat
  minimum does not fit an App Store subscription, and the channel is undecided.
- **Sandbox purchases and real minutes.** The event carries
  `environment: PRODUCTION | SANDBOX`. Granting on sandbox means anyone with a
  tester account mints minutes against production; refusing it means a staging
  deployment sharing the production database cannot be tested end to end. Undecided
  — the handler slice needs an answer.
- ~~The credit-toward-upgrade rule needs a store mechanism.~~ **Resolved
  2026-08-16.** It needs none: top-up minutes live in their own bucket and are
  untouched by a reset or an upgrade, so a user who tops up and then subscribes
  keeps both. §4.5 point 3 was rewritten from a price discount to a statement of
  what the ledger already does, and no code changed.
