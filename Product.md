# Product Specification: Flintroom

<!-- impeccable:product-schema 1 -->

**The room that grills you before the room that matters.**

Flintroom is a mobile-first, hands-free rehearsal application for high-stakes speaking situations. Where existing tools measure *delivery* — filler words, pace, eye contact — Flintroom attacks *substance*. A multi-agent AI panel interrogates the user's argument in real time, challenges their numbers, and catches contradictions between what they say out loud and what their material actually claims. An AI coach then runs a sparring session to rebuild the weak answers.

The premise: the thing people dread is not presenting. It is being asked a question they cannot answer, in front of people who matter.

---

## 1. Positioning

**What Flintroom is not:** a recording utility, a delivery-metrics scorer, or a slide generator. Those categories are saturated, and one competitor (Microsoft Speaker Coach) is free inside PowerPoint.

**What Flintroom is:** an adversarial simulator plus a coach. Pressure first, teaching second.

**Competitive gap.** Yoodli, Orai, VirtualSpeech, Ovation and Speaker Coach all optimize delivery signals because delivery is easy to measure. Almost nobody does grounded, hostile Q&A against the user's own content. That is the wedge, and every product decision should protect it.

---

## 2. Target Audience

Flintroom is a **presentation rehearsal product**, not a fundraising product. The founder pitch is one high-intensity case, not the definition of the market — and it is the smallest of the segments below. Anyone who has to stand up and defend an argument is a user.

**Primary (v1) — all equal weight:**
- **Corporate and executive presenters** — board presentations, exec readouts, strategy pitches, quarterly business reviews, steering committee updates. The largest segment by volume, and the one where the audience is genuinely hostile on a recurring basis.
- **Product managers and internal champions** — launch reviews, roadmap defenses, budget and headcount requests.
- **Consultants, freelancers, and agency leads** — contract bids, client defenses, renewal conversations.
- **Startup founders** — angel, seed, and venture rounds; demo day. Highest intensity, smallest population.

**Secondary (v1, low build cost):**
- **Students and academics** — thesis defense, viva, conference Q&A.

**Implication for messaging.** Positioning Flintroom as "pitch practice for founders" caps the market at the narrowest segment and makes the corporate buyer assume it is not for them. Lead with the situation ("you are about to be grilled"), not the job title. The name helps here — it says nothing about pitching.

**Deferred (v2, engine already supports it):**
- Job interview panels, performance reviews, salary negotiation, sales objection handling, difficult manager conversations.

**Explicitly out of scope:** social or dating practice. It fractures the brand, targets a different buyer, and pulls the product toward the companion-app category. The engine's value is adversarial pressure, which does not transfer to that use case.

**Channel note.** The highest-leverage acquisition path is not consumer. Corporate L&D and enablement teams, accelerators, and incubators buy seats for whole cohorts. One program lead or L&D manager is worth several hundred individual signups — and corporate L&D has both the larger budget and the more repeatable need.

---

## 3. Core Features

### 3.1 Panel Setup ("Character Select")

Users assemble a panel from **pre-built archetypes**, not from real people.

Example archetypes:
- The Growth Maximalist — obsessed with TAM, velocity, and why-now.
- The Margin-Obsessed CFO — attacks unit economics, CAC payback, burn.
- The Technical Skeptic — probes feasibility, architecture, and defensibility.
- The Distracted Executive — half-listening, interrupts, wants the point in one sentence.
- The Internal Blocker — the peer whose team loses budget if your proposal wins.

**Panel composition matters.** A uniformly hostile panel is less useful and less realistic than a mixed room. Ship with a champion, a skeptic, and a neutral, and let them disagree with each other.

> **Removed from the original spec: dynamic social-profile scraping.**
> Building a simulated version of a named real person from LinkedIn/X data carries right-of-publicity exposure, platform ToS violations, GDPR problems, and reputational risk in a small, talkative investor community. It is also unnecessary — the training value lives in the *archetype and thesis*, not the identity.
> **Permitted substitute:** the user may paste their own text describing the audience ("my VP hates anything that adds headcount"), or paste a publicly published fund thesis, as free-text context. User-supplied, not app-scraped.

### 3.2 Context Ingestion

Voice is the primary input. Material is an optional enrichment that makes the panel sharper.

- **Pitch directly** — no upload required. Speak, and the panel goes to work.
- **Attach material** — PDF or PPTX via the **native OS file picker** (iOS Files / Android SAF). This exposes Drive, Dropbox, and iCloud without a Google API integration.
- **Paste text** — instant, zero-friction.
- **Photo of a slide or whiteboard** — vision model extraction; well-suited to mobile.

> **Removed: direct Google Drive OAuth.** Drive scopes are restricted, verification can take weeks and may require a security assessment, and unverified apps hit a warning screen and a 100-user cap. The native picker delivers the same user outcome at zero integration cost. Revisit post-launch.

Parsed content is stored per-slide — claims, figures, and chart data — so that challenges can cite a specific source.

### 3.3 The Interrogation (Live Loop)

Hands-free. The phone sits on the desk; the user speaks naturally.

- **Low-latency conversational voice** with barge-in, so panelists can interrupt mid-sentence the way real rooms do.
- **Auditor Agent (background fact-checking).** A background model maps the live transcript against ingested material and flags contradictions, unsupported claims, and figures that moved between the deck and the spoken answer.
- **Grounded challenges.** Every question should trace back to something the user said or attached. Generic hard questions feel synthetic within two minutes and are the primary retention killer.
- **Targeted interruption.** When the Auditor detects a mismatch, the archetype whose domain covers that metric interrupts. The CFO catches the margin contradiction, not the Technical Skeptic.
- **Difficulty calibration.** Escalating intensity across sessions. A first session that destroys the user produces churn, not resilience.

### 3.4 Live UI Feedback

The screen is a secondary display; attention belongs on speaking.

- **Active speaker indicator** — who is talking, who is about to challenge.
- **Room temperature gauge** — a directional read on how the panel is receiving the argument.

> **Naming note:** the original "Investable → Delusional" scale should be retired. It is funny once, insulting on repeat, and meaningless outside investor pitches. Use neutral, transferable language ("Convinced / Skeptical / Losing the room") that works for a board review as well as a seed round.

### 3.5 Debrief and Sparring Mode

This is the part users will pay for. The interrogation creates the problem; this solves it.

**This phase is unmetered** — see §4.1. Only the live interrogation counts against a user's allowance. Coaching runs on a single voice at roughly a third the cost, and nobody should abandon a re-try because a clock is running.

- **Voice coach walkthrough** — a conversational debrief, not a static dashboard.
- **Ranked weak-answer list** — which questions went unanswered, which claims lacked support, where the argument contradicted itself.
- **Sparring mode** — the coach replays a question the user fumbled and has them re-answer on the spot, repeatedly, until the response holds. Teaching, not just scoring.
- **Shareable artifact** — an exportable prep sheet: "the 6 questions you will get, and where your answers are thin." Screenshot-friendly, which drives organic sharing.

### 3.6 Objective Delivery Signals (Bounded)

Audio-derived, and only where tied to the interrogation:

- Pace, pauses, and filler words **mapped to specific questions** — "you sped up 40% answering the CAC question" points at uncertainty. No incumbent can produce this, because they do not know what was asked.

> **Deferred: video and body-language analysis.** It is the commodity layer, it is expensive (streaming, vision inference, sensitive-recording storage), and inferring confidence or credibility from posture and eye contact is scientifically contested and biased against neurodivergent and non-Western speakers. Audio serves the adversarial thesis; video mostly serves a competitor's product category.

---

## 4. Business Model

### 4.1 The Metric: Time Under Fire

**Flintroom sells minutes of interrogation. Everything after the interrogation is unmetered.**

| Phase | Metered? | Why |
|---|---|---|
| **Live interrogation** | Yes — counts against allowance | Multi-agent panel, real-time bidirectional voice, barge-in, background Auditor. This is the cost driver. |
| **Voice debrief** | No | Single coach voice, turn-based, no interruption handling. Roughly a third of the per-minute cost. |
| **Sparring re-tries** | No | Same cheap path as the debrief — and this is where the learning happens. |

A standard session is **up to 12 minutes of interrogation**, followed by a debrief and sparring session the user can stay in as long as they want (soft cap ~20 minutes, extendable).

Three reasons this split is right:

1. **It meters only what actually costs money.** Rationing the cheap single-voice coaching to protect margin on the expensive multi-agent panel would be taxing the wrong thing.
2. **It is psychologically inverted in the user's favour.** The *pressure* is rationed; the *teaching* is unlimited. That is the correct message for a product whose purpose is improvement.
3. **It removes the worst failure mode.** Nobody should abandon a sparring re-try because a clock is running. That is precisely the moment the product earns its subscription.

**Allowance is expressed in minutes, monthly.** Not credits, not weekly. Rehearsal is bursty — someone prepping for demo day or a board review wants five sessions in one week and none for the next three. A weekly reset with no roll-over punishes exactly the behaviour the product exists to serve.

### 4.2 Why the Original Pricing Had to Change

At the stated **$0.08–0.20 per minute**, the original 20-minute token cost **$1.60–4.00** to serve. Against that:

| Original tier | Price | Max tokens/mo | Cost at full use (low end) |
|---|---|---|---|
| Pro | $19/mo | ~40 | ~$64 |
| Executive | $149/yr (~$12.40/mo) | ~60 | ~$96 |
| Booster | $7 one-off | 5 | ~$8 |

Every tier lost money at moderate utilization and the booster pack was underwater on first use. Breakeven required users to burn under a quarter of their allowance — a hope, not a model.

### 4.3 Cost Basis

Working assumptions, **to be replaced with instrumented data in week one**:

- **Interrogation: ~$0.12/min.** Only one panelist speaks at a time, so this is closer to single-stream voice plus additional LLM reasoning than to 3× concurrent synthesis.
- **Debrief + sparring: ~$0.05/min**, averaging ~10 minutes of actual use per session → **~$0.50 per session**.
- **Effective cost per full session:** ~$1.44 interrogation + ~$0.50 coaching ≈ **$1.95**.

The tiers below target **55–65% gross margin at full allowance consumption**, so they stay profitable for the heaviest user rather than relying on light users to subsidize the rest.

---

> ### ⚠️ REQUIRED BEFORE PRICING SHIPS — Cost Instrumentation Task
>
> **Every number in §4.4 and §4.5 is derived from unverified assumptions. Do not publish prices until this task is complete.**
>
> **The load-bearing assumption:** interrogation costs ~$0.12/min because only one panelist speaks at a time, making this closer to single-stream voice plus extra LLM reasoning than to 3× concurrent synthesis. **If ElevenLabs bills per active agent session rather than per synthesized minute, this assumption is wrong and every margin in the tables collapses.**
>
> **Implementation requirement.** Build cost telemetry into the session pipeline from the first working voice loop — not as a later addition. Persist one `session_costs` row per session containing:
>
> | Field | Notes |
> |---|---|
> | `session_id`, `user_id`, `tier` | Join keys |
> | `interrogation_seconds` | Wall-clock, panel active |
> | `tts_characters_synthesized` | Per provider, split by agent |
> | `stt_seconds_processed` | Inbound user audio |
> | `agent_session_count` | Concurrent runtimes instantiated — the field that settles the assumption above |
> | `llm_input_tokens`, `llm_output_tokens` | Split: panel agents vs Auditor vs coach |
> | `auditor_invocations` | Background fact-checking runs |
> | `debrief_seconds`, `sparring_seconds` | Unmetered phases — must still be costed |
> | `provider_reported_cost` | Pulled from provider usage API where available |
> | `computed_cost_usd` | Derived total |
>
> **Acceptance criteria:**
> 1. Run 10 full sessions (varying panel sizes: 1, 2, 3 panelists) with telemetry on.
> 2. Reconcile `computed_cost_usd` against the actual provider invoice — agreement within 10%.
> 3. Report observed cost per interrogation minute at each panel size, and observed cost per unmetered coaching minute.
> 4. Re-derive §4.3–4.5 from the observed figures. If interrogation exceeds **$0.18/min**, the tier allowances must shrink or prices must rise before launch.
>
> **Also measure:** median unmetered coaching duration. The ~10-minute average in §4.3 is a guess, and unmetered time is the model's largest uncontrolled exposure. If the real median runs past 20 minutes, the soft cap in §4.7 needs tightening.
>
> Expose the totals on an internal admin dashboard. Per-session cost visibility is an operational requirement, not a nice-to-have, for a product with variable compute per user.

---

### 4.4 Tiering

Every tier below is designed to be **a complete plan for its user**, not a funnel step. Someone who stays on Starter for two years should be well served, not squeezed.

Cost per interrogation minute, all-in (interrogation + its share of unmetered coaching): **~$0.16**.

| Tier | Price | Interrogation time/mo | ≈ Sessions | Cost at full use | Margin |
|---|---|---|---|---|---|
| **Free** | $0 | 15 min, lifetime | 1 full session | ~$2.30 | — |
| **Starter** | $29/mo | **90 min** | ~7 | ~$14.55 | 50% |
| **Pro** | $59/mo | **3 hours** | ~15 | ~$29.10 | 51% |
| **Pro Annual** | $599/yr (~$50/mo) | 3 hours | ~15 | ~$29.10 | 42% |
| **Teams / Cohort** | From $25/seat/mo (min. 10 seats) | 90 min/seat | ~7 | ~$14.55 | 42% |

All tiers include unmetered debrief and sparring.

Notes on the shape:

- **Starter covers a real month of work,** not a single event. Preparing one significant presentation properly means a rough first run, three or four rounds fixing weak answers, and a clean final pass — that alone is close to an hour. 90 minutes leaves room for a second presentation or an unplanned one.
- **The free tier gives one complete experience**, not three truncated tastes. People convert after feeling the value, not after sampling it — and the sparring debrief is what sells the subscription, so it must be reachable for free.
- **Per-minute pricing is deliberately near-flat across Starter and Pro** (~$0.32 vs ~$0.33). Live voice compute does not get cheaper at volume, so a steep per-minute discount at the top tier would just erode margin. **Pro's value is in capability, not a bulk rate** — priority voice queue, full session history, unlimited material storage, prep-sheet export, custom archetypes. Sell it that way.
- **Teams is priced at Starter level per seat, not below it.** Undercutting your own standalone plan trains buyers to route around it. The commercial advantage of Teams is volume and near-zero acquisition cost, not a discount.

### 4.5 Top-Ups (Over-Limit Flow)

When a user exhausts their monthly minutes, the session does not stop dead. They are offered an immediate top-up, purchased in-app, applied instantly.

| Pack | Price | Interrogation time | Per min | Cost | Margin |
|---|---|---|---|---|---|
| Quick top-up | $9 | 20 min | $0.45 | ~$3.20 | 64% |
| Demo-day pack | $35 | 90 min | $0.39 | ~$14.55 | 58% |
| Cohort block | $99 | 300 min | $0.33 | ~$48.50 | 51% |

Top-up minutes are priced above the subscription per-minute rate (~$0.32) so that upgrading always looks better than repeat top-ups. The cohort block matches the subscription rate deliberately — it is a bulk purchase by an organization, not an urgency purchase by an individual.

**The smallest pack must feel small.** $9 for 20 minutes is an impulse decision; a larger minimum turns a moment of need into a moment of resentment.

#### The Credit-Toward-Upgrade Rule (required)

Top-ups carry the highest margin in the product and are bought at the user's worst moment — out of minutes, presenting tomorrow. Charging a premium there is defensible only if the product actively steers users away from repeating it.

**Implementation:**

1. On the **first** top-up, present the upgrade alongside it, and state plainly that the minutes are kept: *"$35 for 90 minutes now — or $59 for 3 hours every month. Either way the 90 minutes stay yours."*
2. On the **second** top-up in any rolling 30-day window, make the upgrade the default option and the top-up the secondary one.
3. **The minutes are the credit.** Top-up minutes never expire and are untouched by an upgrade, so a user who tops up and then subscribes holds both — 90 bought minutes plus a full monthly allowance, and the 90 survive every reset after that.
4. Never gate the top-up behind the upgrade prompt. One tap to decline, always.

A user who tops up three times in a month is a pricing failure, not a revenue win. The plan should have caught them at the first.

**Revised 2026-08-16.** Point 3 previously promised that top-up spend would be *"deducted from the first month of any upgrade"* — a price discount. Two things were wrong with it. Neither store will discount a subscription on account of a prior consumable purchase, so the promise could not be kept at the till without per-user promotional offers on both platforms. And it was compensating for a loss that does not occur: it was written as though upgrading stranded the top-up the way a monthly allowance is stranded at a reset, but the ledger keeps top-up minutes in their own bucket precisely so that never happens.

What remains is a real premium — those minutes were bought at $0.39 against Pro's $0.33, about $5 on a $35 pack — and the answer to it is the upgrade prompt itself rather than a credit. The rule's purpose is unchanged: steer a repeat top-up toward the plan that should have caught them.

Design rules for the flow:

- **Top-up minutes never expire.** They sit alongside the monthly allowance.
- **Monthly allowance is consumed first**, then the top-up balance. Users should never accidentally burn purchased minutes while free ones remain.
- **Never interrupt a live session.** If a user runs out mid-interrogation, let the panel finish and settle afterwards. Cutting off a panelist mid-question to show a paywall destroys the one experience the product sells.
- **Prompt the upgrade with the credit applied** — see the Credit-Toward-Upgrade Rule above. Farming your most engaged users is a short game.
- **Optional auto-refill**, off by default, with a user-set monthly ceiling. Silent auto-charging is the fastest route to chargebacks and one-star reviews.

### 4.6 Presenting the Price

The economics above are sound; the *framing* determines whether they feel generous or stingy.

- **Lead with the largest honest unit.** "3 hours of executive-level interrogation every month" reads generously. "15 credits" reads rationed. Identical product.
- **Show the alternative on the pricing page.** A presentation coach or pitch trainer runs $150–400/hour. Flintroom is not competing with free — it is competing with something twenty times the price, and saying so out loud reframes $59 as cheap.
- **Anchor against the stakes, not the substitutes.** A board presentation that goes badly costs a promotion cycle; a round that dies costs a company.
- **Never display a depleting counter.** "48 minutes available" not "2 of 5 credits left." Depletion framing makes users ration, and rationing users churn.
- **Say what is unlimited, prominently.** Unmetered coaching and sparring is a genuine differentiator and should sit at the top of every tier card, not in a footnote.

### 4.7 Safeguards

- Interrogation stops at the session limit; the coach delivers a spoken handover into the debrief rather than cutting audio dead.
- Idle/silence detection ends abandoned sessions and refunds the minutes automatically.
- Per-account daily spend ceiling as a runaway-cost circuit breaker.
- Minutes are decremented as consumed, not reserved upfront, and refunded automatically on technical failure.
- Soft cap on unmetered coaching (~20 min) with a friendly extend prompt, so the "unlimited" path cannot be abused by an idle open session.
- **Instrument real per-session cost from week one.** Every figure above rests on vendor list-rate assumptions. Replace them with observed data and re-derive the tables before launch.
## 5. Technology Stack

| Layer | Technology | Function |
|---|---|---|
| Frontend | Expo / React Native | iOS + Android; native mic control, audio streaming |
| Backend API | FastAPI (Python) | Async endpoints, extraction, ledger, streaming webhooks |
| Orchestration | LangGraph / PydanticAI | Agent state machine, panel turn-taking, Auditor workflow |
| Voice | **ElevenLabs Agents** (conversational loop + panelist voice identity), Gemini Live as fallback | Bidirectional streaming, barge-in, distinct per-archetype voices |
| Ledger DB | Supabase (PostgreSQL) | Token decrements under strict RLS |
| Billing | RevenueCat | Subscriptions, entitlements, paywalls |
| Document parsing | PDF/PPTX extraction + vision model for slide photos | Per-slide claim and figure storage |

> **Removed: Exa.ai / Firecrawl profile scraping**, following the removal of the social-profile feature.

### 5.1 Note on the Voice Provider

**Decision: ElevenLabs.** It ships a real conversational agent runtime with native barge-in rather than TTS alone, which matters because interruption is a headline feature here, not a nicety. Voice range is also strong enough to give each archetype a distinct, recognizable identity — important when three panelists share a session and the user cannot see the screen.

Secondary benefit: ElevenLabs is a Shipaton sponsor, so check the Ship Kit for credits and any sponsor prize category before finalizing the integration.

Two things to verify early regardless of provider:

1. **Latency under concurrent multi-agent load.** Three distinct voices in one live session is heavier than single-voice TTS. Measure it in week one, not week six.
2. **Cost per minute at real concurrency.** Every pricing number in §4 rests on the blended per-minute assumption. Confirm against actual invoices.

Keep the voice layer behind an interface so Gemini Live (or another provider) can be swapped in if latency or cost fails to hold.

### 5.2 Architecture Principle

Build the panel internally as **persona + attack strategy + grounding context**. Then "hostile VC" and "manager who disagrees with your proposal" are configuration, not new code. Keep the internals general and the shipped UI ruthlessly narrow — this makes the v2 expansion into professional conversations a week's work instead of a rewrite.

Keep the backend free of mobile-only assumptions (device-coupled auth, push-token dependencies, phone-specific audio formats) so a web client can be added post-hackathon without a rewrite.

---

## 6. User Flow

```
[1] Setup ──► Token check ──► Pick panel ──► (optional) attach material
                                                  │
                                                  ▼
[2] Live simulation (METERED) ──► Hands-free pitching ──► Bidirectional audio stream
         │                                              │
         ▼                                              ▼
   Auditor cross-checks claims                Active speaker + room temperature
         │
         ▼
[3] Interruption ──► The relevant archetype challenges the specific claim
         │
         ▼
[4] Debrief (UNMETERED) ──► Coach walkthrough ──► Sparring re-tries ──► Prep sheet export
```

---

## 7. Build Plan

The original 48-hour plan does not match the actual constraint. **Shipaton 2026 runs August–September** — roughly two months, and it requires shipping to real app stores. Plan accordingly.

**Weeks 1–2 — Foundations**
Supabase schema and token ledger with RLS. FastAPI endpoints. Document extraction. RevenueCat wired early, not the night before — a dedicated award exists for monetization execution.

**Weeks 3–4 — The Voice Loop**
ElevenLabs Agents channel; clean bidirectional streaming from Expo; playback stability; barge-in verified end-to-end. **Ship the `session_costs` telemetry table alongside the first working voice loop** — see the instrumentation task in §4.3. Cost visibility must exist before the first ten test sessions, not after. This is the highest-risk block; if it slips, everything slips.

**Weeks 5–6 — Panel and Auditor**
LangGraph orchestration, turn-taking, inter-panelist disagreement. Auditor cross-referencing transcript against material. Grounded challenge generation. Difficulty calibration.

**Week 7 — Debrief and Sparring**
Coach walkthrough, ranked weak answers, re-try loop, exportable prep sheet.

**Week 8 — Polish, Store, Demo**
UI refinement, onboarding, privacy policy and data-handling documentation (expect scrutiny on an AI app requesting mic access), **app store review with a week of slack**, and a high-fidelity demo video.

**Continuous — Traction**
The Grand Prize rewards traction and growth momentum. Land one accelerator cohort during the build window; it validates the product and serves the prize criteria simultaneously. Post the build-in-public journey throughout — there is a dedicated award, and it costs only posting effort.

---

## 8. Open Risks

1. **Do people tolerate being attacked?** The riskiest assumption in the product. Users may say they want honest sparring and churn because it feels bad. Validate with real founders before the engine is finished.
2. **Grounding quality.** Ungrounded generic questions kill retention faster than any UI flaw.
3. **Voice latency.** Below roughly 1.5 seconds the illusion holds; above it, the room feels fake.
4. **Unit economics.** The ~$0.12/min interrogation assumption is unverified and every tier margin depends on it. Complete the cost instrumentation task in §4.3 before publishing prices. Secondary exposure: unmetered coaching time is uncapped by design and only softly bounded — measure the real median.
5. **Store review.** Mic-access AI apps draw scrutiny. Privacy policy and recording-retention answers ready in advance.
6. **Scope creep.** Presentations only for v1. Professional conversations are a post-launch expansion justified by usage data, not enthusiasm.

---

## 9. Product Record

Durable product truth for design and build work. Sections above are the full spec; this section adds the facts they did not state and points at the ones they did, so there is one authority rather than two. Confirmed 2026-08-11.

### Platform

ios

One shared Flintroom design language across iOS and Android, with **iOS as the reference platform** — one component set, brand-forward, not two per-OS design languages. Android ships the same language; where a platform affordance genuinely differs (back gesture, share sheet, permission dialogs), follow the host OS rather than porting iOS chrome. Mobile is the only v1 client; §5.2's "keep a web client possible" is a backend constraint, not a v1 surface.

### Stack

Expo / React Native (confirmed, §5). UI is built against the design tokens in `design-guide/pitchgo_design_system/DESIGN.md`, not a component library chosen later.

### Users

See §2. Primary v1, equal weight: corporate/executive presenters, product managers, consultants/agency leads, startup founders. Secondary: students and academics. The buying channel that matters most is corporate L&D and accelerator cohorts, not individual consumers.

### Product Purpose

See the opening statement and §1. Adversarial simulator first, coach second: pressure, then teaching.

### Positioning

See §1. The defensible mechanism is **grounded hostile Q&A against the user's own material** — a challenge that traces to a specific claim, figure, or slide the user supplied. Delivery-metrics scoring is the commodity layer and is not the product.

### Operating Context

See §3 and §6. The physical scene is the load-bearing fact: **the phone sits face-down-flat on a desk and the user is speaking to a room, not looking at the screen.** Anything requiring sustained gaze or touch during an interrogation is designed against the actual usage posture. The screen is glanceable at best during the live phase, and fully attended only in setup, debrief, and sparring.

### Capabilities and Constraints

See §3 (features), §4 (metering and pricing), §5 (stack), and `CLAUDE.md` (locked architecture decisions).

Durable constraints that bind design work specifically:

- **Minutes, never tokens or credits.** The metered unit is interrogation minutes. Never render a depleting counter (§4.6); show remaining minutes plainly and generously.
- **Never interrupt a live interrogation with a paywall or upsell** (§4.5). Settle after the panel finishes.
- **Room temperature stays neutral and transferable** — "Convinced / Skeptical / Losing the room." The retired "Investable → Delusional" scale and any investment-verdict framing do not return; they break outside a pitch context and this product is not pitch-only.
- **Domain vocabulary is fixed:** Panel, Archetype, Auditor, Interrogation, Debrief, Sparring, Room temperature, Grounded challenge. No synonyms, no abbreviations.
- **Panelists are pre-built archetypes.** No real named people, no scraped profiles — user-supplied free text is the only permitted audience enrichment.
- **The coach is conversational in manner, scoped in subject.** Debrief and sparring are real back-and-forth — follow-ups, clarifications, re-answers, the coach pushing back (§3.5 is explicit that this is a conversation, not a dashboard). What is bounded is the *subject*: the coach is grounded in that session's artifacts — transcript, ranked weak answers, Auditor findings, ingested material. It does not review fresh material it was never handed, because listening to an argument and challenging it **is** an interrogation, and interrogation is the metered phase. A user asking the coach to hear a new pitch is asking for a session; the coach says so and offers to start one.

  Two reasons this is a constraint and not a preference. **It closes a revenue arbitrage:** an unscoped coach lets any user get unlimited free pitch review and never touch the metered panel. **It protects the wedge:** open-ended "listen and tell me how I did" is precisely the competitor product (§1), and an unscoped coach would ship it inside the free tier. Scope is also what makes the unmetered promise safe to state plainly — the bound is subject matter, not a clock, so §4.6 can keep saying coaching is unlimited and be telling the truth.

Undecided, do not invent: final tier names and prices as shown to users (§4.4 is unverified until the cost-instrumentation task closes), recording-retention window, onboarding length.

### Brand Commitments

- **Name:** Flintroom. **Tagline:** "The room that grills you before the room that matters." Both confirmed.
- **Design tokens are binding.** `design-guide/pitchgo_design_system/DESIGN.md` — warm off-white surfaces, burnt-orange primary, Hanken Grotesk, 28px container radius, pill controls, ambient rather than hard-edged elevation — is brand truth and carries forward under the Flintroom name.
- **The eight screen mockups in `design-guide/<screen>/` are stale, not binding.** They predate the rename ("PitchGo AI", "PitchForge AI") and encode retired product decisions: a "120 Tokens" counter and "Tokens Remaining" metric (`home/code.html`), an `investment_verdict_dashboard/` screen, an "Avg. Likelihood %" score, and founder-pitch-only copy. Use them as layout and density reference; do not reproduce their content model. `billing_tokens/` in particular must be rebuilt around minutes.
- **No logo or wordmark asset exists yet.** Do not fabricate one or imply it exists.
- **Voice:** direct and unsentimental, the way a good coach speaks after a hard session — never cruel, never gamified-cheerful. The product's tone problem is that being attacked is already uncomfortable (§8, risk 1); the interface's job is to make the discomfort feel deliberate and worth it, not to soften it into encouragement or amplify it into humiliation.

### Evidence on Hand

- **Real:** the product spec (this file), the design tokens, and eight HTML/PNG screen references of the previous product identity.
- **Absent — do not fabricate:** users, sessions, testimonials, case studies, logos of customers or accelerators, latency measurements, retention data, and observed cost figures. Every number in §4.3–4.5 is an unverified vendor list-rate assumption until the instrumentation task closes; no marketing or UI surface may state them as measured.
- **The mockup imagery is placeholder.** The hero images in the screen references are AI-generated stock hosted on Google's CDN. They are not licensed assets and must not ship.

### Product Principles

1. **Ground every challenge or don't ask it.** A question that cannot cite what the user said or attached is the failure mode that kills retention, not a lesser version of a good question.
2. **Meter the pressure, never the teaching.** The interrogation is rationed; debrief and sparring are unlimited. Every pricing, copy, and interface decision follows from that inversion.
3. **Design for the desk, not the hand.** The live phase is hands-free and eyes-up. Glanceable or nothing.
4. **Hostility is the product; humiliation is the churn.** Escalate difficulty across sessions, mix the panel, and always route the user into a path that rebuilds the answer.
5. **Lead with the situation, not the job title.** "You are about to be grilled" travels across board reviews, client defenses, and seed rounds; "pitch practice" does not.

### Accessibility & Inclusion

- **WCAG 2.2 AA** as the floor: contrast, target size (44×44pt minimum), focus order, and screen-reader labelling on every surface.
- **Live captions are required, not deferred.** A voice-only interrogation is unusable to deaf and hard-of-hearing users; a caption/transcript track for panel speech is a v1 requirement, and it also strengthens the App Store accessibility and data-handling answers (§8, risk 5).
- Honour Dynamic Type and system contrast settings; layouts must survive the largest accessibility text sizes without truncating a panelist's question.
- Delivery signals (pace, pauses, fillers, §3.6) are audio-derived and framed as observations tied to specific questions — never as a judgment of competence, and never extended into posture, gaze, or affect inference (§3.6, deferred).
