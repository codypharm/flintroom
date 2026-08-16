# Setting up billing: App Store Connect, Play, RevenueCat

**Status:** setup guide, not a decision record. The decisions are `Product.md` §4.4–4.5
and `docs/minutes-ledger-and-sessions.md`; this is the sequence of dashboard work
that turns them into products a phone can buy.

**The deliverable** is a list of store product identifiers and entitlement
identifiers, which is what `billing/tiers.py` maps to tiers. Nothing generates
them — they are strings you choose, typed into Apple and Google, and mirrored by
RevenueCat.

Do it in the order below. Two steps have multi-day latency and block everything
after them, and both are administrative rather than technical.

---

## 0. The long poles, started first

Neither of these is work. Both are waiting, and everything else waits on them.

**Apple — the Paid Applications Agreement.** App Store Connect → Business (older
UI: Agreements, Tax, and Banking). You need the agreement accepted, a bank
account attached, and tax forms completed. **In-app purchases do not function
until this is active**, including in sandbox, and the failure is confusing: the
product simply is not returned to the app, as though the identifier were wrong.
Bank verification can take days.

**Google — a release on a track.** Play Console will not show the Monetise
section until the app exists and at least one build has been uploaded to a track
(internal testing is enough, and it does not have to be reviewed or public). If
the Expo app is not yet building an AAB, this is the thing to start early.

While those settle, everything in §1 and §4 can be done.

---

## 1. Decide the identifiers once

Apple product identifiers **cannot be renamed, reused, or recreated after
deletion** — ever, across the lifetime of the account. Choose the scheme you want
to live with before typing any of them.

The seven products `Product.md` §4.4–4.5 specifies:

| Plan | Kind | Suggested identifier |
| --- | --- | --- |
| Starter, $29/mo | Auto-renewable subscription | `flintroom_starter_monthly` |
| Pro, $59/mo | Auto-renewable subscription | `flintroom_pro_monthly` |
| Pro Annual, $599/yr | Auto-renewable subscription | `flintroom_pro_annual` |
| Teams, $25/seat/mo | Auto-renewable subscription | `flintroom_teams_monthly` |
| Quick top-up, $9 / 20 min | **Consumable** | `flintroom_topup_20` |
| Demo-day pack, $35 / 90 min | **Consumable** | `flintroom_topup_90` |
| Cohort block, $99 / 300 min | **Consumable** | `flintroom_topup_300` |

**Consumable, not non-consumable, for the three packs.** §4.5 says top-up minutes
never expire and the same pack is bought repeatedly. A non-consumable can be
bought once per account and is restorable forever, which is the opposite of both.

**Teams is a placeholder here.** Per-seat billing with a ten-seat minimum is not
an ordinary App Store subscription, and §4.4's Teams tier probably sells through
a different channel entirely. Create the other six and leave Teams until there is
a buyer; `docs/ingestion.md` and the ledger already treat it as a tier, so nothing
breaks by deferring the product.

---

## 2. App Store Connect

### 2.1 Subscription group

App Store Connect → your app → **Subscriptions** → create **one** group, e.g.
`Flintroom Plans`.

**Starter, Pro and Pro Annual all go in the same group.** Subscriptions within a
group are mutually exclusive, and Apple handles upgrade, downgrade and proration
between them automatically. In separate groups a user can hold two at once and be
charged twice, which is a support ticket and a refund rather than an upgrade.

The group's display name is user-visible in the subscription management screen.

### 2.2 Each subscription

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

### 2.3 The three consumables

In-App Purchases → **Consumable**. Same fields, no group, no duration.

### 2.4 Sandbox testers

Users and Access → **Sandbox** → Test Accounts. Use an email address that is not
an Apple ID already. On the device, sign in under Settings → App Store → Sandbox
Account, **not** the main Apple ID.

A sandbox subscription renews on an accelerated clock — a month is minutes — which
is exactly what is needed to see `RENEWAL` and `EXPIRATION` events without waiting.

### 2.5 Before you have any of this

Xcode's **StoreKit configuration file** fakes products locally with no App Store
Connect involvement at all. Useful for building the paywall UI early, and it
produces no webhooks — so it proves nothing about the backend.

---

## 3. Google Play Console

Do this after §0's release is uploaded, or the menus will not appear.

- **Subscriptions** → create one per plan. Play's model is a *subscription* with
  one or more **base plans**; create a single auto-renewing base plan per
  subscription unless there is a reason not to.
- **In-app products** → the three top-ups, as *consumable* managed products.
- **Licence testers** — Play Console → Settings → Licence testing. Testers can
  buy without being charged.

**The identifier Play reports may not be the one you typed.** With base plans, a
purchase can be reported as `subscription_id:base_plan_id`. Do not guess at it —
see §5.

---

## 4. RevenueCat

### 4.1 Project and apps

Create a project, then add an app per platform.

- **iOS** needs the bundle identifier and an **In-App Purchase Key** (App Store
  Connect → Users and Access → Integrations → In-App Purchase). The older
  app-specific shared secret still works; the key is what Apple points new
  integrations at.
- **Android** needs the package name and a **Google Cloud service account** with
  access to the Play Developer API, invited into Play Console with financial-data
  permission. This is the fiddliest step on either platform and RevenueCat's own
  guide is the one to follow.

Also configure **Apple App Store Server Notifications** to point at RevenueCat, so
refunds and billing failures reach it without a poll.

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

Offerings and packages drive what the paywall displays. They matter to the app,
not to the backend — nothing in this repo reads them. Configure them when the
paywall is built.

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
- **The credit-toward-upgrade rule** (§4.5) has no store mechanism behind it yet.
  Apple will not discount a subscription because of a prior consumable purchase,
  so honouring "we'll put this $35 toward it" means crediting minutes on our side
  after the upgrade lands, not a cheaper price at the till. That is a ledger
  decision and it is not made.
