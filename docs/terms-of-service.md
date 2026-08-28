# Terms of Service — derivation and open items

**Status: drafted 2026-08-28, published at `web/terms.html` the same day.**
Like the privacy policy, every operative clause is derived from what the
product actually does, so the published page states nothing the code
contradicts. This file records where each clause comes from and what only
counsel can finish.

| Published clause | Derived from |
| --- | --- |
| "Not professional advice; AI can be wrong" | Observed live 2026-08-27 — the CFO derived a meaningless quotient and announced a wrong verdict. The challenge-not-verdict prompt rule reduces it; the terms disclaim what a prompt cannot eliminate |
| "Confrontational by design" | The product thesis (Product.md §1), restated so being grilled cannot be framed as a defect |
| Minutes deducted as used, refunded on technical failure | CLAUDE.md Metering Rules; `REFUND_REASONS`, the reaper's refund paths |
| Top-ups never expire; allowance consumed first | Product.md §4.5 point 3; `billing/tiers.py` |
| Payment, renewal, cancellation, money refunds via the store | RevenueCat + Google Play billing; we never touch card details |
| Limited processing licence over user material | The pipeline in docs/ingestion.md and the provider table in docs/privacy-policy.md — the licence is scoped to "solely to provide Flintroom" because the no-training toggles (2026-08-27) make anything broader unnecessary |
| 18+ | The Play target-audience declaration (18 and over, 2026-08-27) |
| Account deletion pointer | docs/account-deletion.md; the /delete-account page |

## [LAWYER] — open items for the eventual review

- **No governing-law / jurisdiction clause is published.** Deliberate: naming
  a jurisdiction before the business's registration is settled would be a
  guess. Add it when the entity exists on paper.
- **The liability cap** ("amounts paid in the twelve months before the
  claim") is the standard consumer-app shape, unreviewed. Some jurisdictions
  constrain caps for consumers; the "nothing limits what cannot lawfully be
  limited" saver is doing load until reviewed.
- **No arbitration/class-waiver clause.** Deliberately omitted — it is the
  clause most likely to be wrong per-jurisdiction and least needed at this
  scale. Counsel's call whether to add one.
- The change-notification promise ("in the app or by the contact on your
  account") must stay true — if terms change materially, that notice has to
  actually go out (Resend is wired for transactional email).

## Where users agree

The sign-in screen carries "By continuing, you agree to the Terms of Service
and Privacy Policy" with both linked — the sign-in-wrap pattern, agreement
placed at the point of account creation. The recording disclosure remains a
separate, stronger consent: a pass-through screen before the microphone
permission (`app/src/lib/consent/entry.ts`).
