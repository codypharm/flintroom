# Flintroom

**The room that grills you before the room that matters.**

## Authority

**Human is architect. Agent is senior engineer.**

- Check `Product.md` before every task — it is the source of truth for scope, pricing, and positioning. Cross-reference `design-guide/` before touching any screen.
- Before starting any feature: invoke the `grill-me` skill to stress-test requirements as developer questions, not just decide.
- Before building or touching anything visual: invoke the `impeccable` skill and read the relevant screen folder in `design-guide/` first (see Design System below).
- Before debugging: invoke the `diagnose` skill.
- Use the `to-prd` skill when a feature is described loosely enough that it needs to be turned into a proper spec before implementation.
- Every feature is test-driven: write failing test first, then implementation. Invoke the `tdd` skill before any feature work.
- Never make architecture decisions autonomously — present 2–3 options with trade-offs, human chooses.
- Never bulk-generate code. One module, one feature, one migration at a time.
- Remind human to commit after each meaningful change.
- If stuck or ambiguous: ask. Never guess on product behaviour — especially anything touching the interrogation panel's tone, the metering boundary (§4.1), or pricing.
- Flag risks — cost overrun, latency, data/recording privacy, App Store review exposure — immediately and explicitly. See Open Risks below.

---

## Project

Flintroom is a mobile-first, hands-free rehearsal app for high-stakes speaking situations. A multi-agent AI panel interrogates the user's argument in real time, challenges their numbers, and catches contradictions between what they say and what their material claims. An AI coach then runs a sparring session to rebuild the weak answers.

**The wedge:** competitors (Yoodli, Orai, VirtualSpeech, Ovation, Microsoft Speaker Coach) score *delivery* — filler words, pace, eye contact. Flintroom attacks *substance* — grounded, hostile Q&A against the user's own content. Protect this wedge in every product decision; do not let the product drift toward a delivery-metrics scorer or a companion/social app.

**Primary audience (v1, equal weight):** corporate/executive presenters, product managers, consultants/freelancers, startup founders. **Secondary:** students/academics. **Deferred to v2:** job interviews, performance reviews, salary negotiation, sales objection handling. **Out of scope:** social/dating practice — do not build toward it.

### Key Docs

| Doc | Path | Purpose |
| --- | --- | --- |
| Product Spec | `Product.md` | Full product spec — source of truth. Positioning, features, pricing, stack, build plan, risks. |
| Ledger & sessions | `docs/minutes-ledger-and-sessions.md` | Resolved design for the minutes ledger and session state machine, with rationale. Read before touching billing, sessions, or the metering boundary. |
| Deferred scale work | `docs/deferred-scale-work.md` | Scale work considered and declined, each with the signal that should reopen it. Read before adding sharding, replicas, caching, or queueing — and before anything that would break the per-user sharding property. |
| Auditor grounding | `docs/auditor-grounding.md` | What the Auditor cross-checks against, with and without attached material. Read before touching the Auditor, claim extraction, or targeted interruption. |
| Context ingestion | `docs/ingestion.md` | Resolved design for attached material — ownership, the async extraction lifecycle, the storage interface, the extraction model behind `EXTRACTION_PROVIDER`, and why the source document is deleted once extraction succeeds. Read before touching ingestion, object storage, or anything that produces a claim. |
| Billing setup | `docs/billing-setup.md` | The Play, RevenueCat and (later) App Store Connect dashboard work that turns §4.4–4.5 into products a phone can buy. Google is wired first — $25 once against Apple's $99/year, and the backend is store-agnostic. Read before creating a product identifier, since neither store lets one be reused. |
| Voice cost | `docs/voice-cost.md` | What a room costs, measured rather than assumed — where the voice bill actually goes, and why the panel's word cap is not a cost lever. Read before changing the word limit, the synthesis vendor, or any price in §4.4. |
| Deployment | `docs/deployment.md` | Requirements that no test enforces and that fail quietly — proxy headers for the rate limiter, alerting on sweep silence, agent configuration, and how to give a user minutes by hand (`scripts/grant_minutes.py`, never SQL). Read before deploying anywhere, before changing rate limiting or the sweep loop, and whenever someone needs minutes granted: a promo, a tester, a complaint. |
| Echo cancellation | `docs/echo-cancellation.md` | Why the audio layer is an owned native module (`app/modules/room-audio`) and what its two declarations protect. Android AEC is a property of the recorder/player **pair** — `VOICE_COMMUNICATION` source plus `USAGE_VOICE_COMMUNICATION` usage — and no test can fail when an acoustic property regresses, so the measurements in the doc are the protection. Read before touching `app/modules/room-audio`, `app/src/lib/voice/stack.ts`, or the audio streams. |
| Onboarding | `docs/onboarding.md` | Resolved first-launch flow — survey shape, sign-in placement, mic-permission timing, the free-tier grant, and why streaks were rejected. Read before touching onboarding, auth, or the free grant. |
| Privacy policy | `docs/privacy-policy.md` | The disclosure text, assembled from what the code does rather than from intent, with every claim traced to the file that enforces it. A **working draft** — unreviewed by a lawyer, carrying `[CONFIRM]` markers that must be resolved before publication. Read before answering an App Store review question; update whenever a retention window, a provider, or a user control changes. |
| Session retention | `docs/session-retention.md` | What survives a room and for how long — transcript for the life of the account, the full mixed recording on a per-tier window, and why playback plays the stored file rather than re-synthesising it. Fixes the retention window `Product.md` §413 left undecided, and settles the production object-storage vendor. Read before touching the relay's audio path, the mixer, retention, or anything that persists a transcript. |
| Debrief and sparring | `docs/debrief-and-sparring.md` | Resolved design for Phase 4 — when weak answers are computed, why code sets the ranking floor and the model only orders the remainder, how the coach's scope is bounded by cite-or-redirect rather than by a classifier, and why the debrief is turn-based HTTP rather than a socket. Read before touching the coach, weak answers, sparring, or the prep sheet — and before adding any model call that asks for a judgement rather than an extraction. |
| Rehearsals | `docs/rehearsals.md` | Resolved design for grouping rooms by the argument they are attempts at — why a lineage is a group id every room carries rather than a table, why the client names a *room* to repeat and never a group, and why any room may name the lineage with the newest name winning. Read before touching `sessions.rehearsal_id`, `sessions.rehearsal_name`, `modules/sessions/rehearsals.py`, the Progress screen, or "Run it again". |
| Difficulty calibration | `docs/difficulty-calibration.md` | Resolved design for #55 — what the dial is made of (two integers code enforces, never an adjective in a prompt), why the signal is only the weak answers the presenter was at fault for, the three-rung ladder with today's shipped room in the middle, and why the press cap never reaches zero. Read before touching `_SELECTION_INSTRUCTION` rule 2, `dispute.DISPUTES_PER_ROOM`, or anything that would make one user's room differ from another's. |
| Audience context | `docs/audience-context.md` | Resolved design for #66 — the presenter's own sentence about the room they are facing, and the permitted substitute for profile scraping. Why the panel is *shaped* by it and never says it aloud, why it enters at the composer and never as a claim or to the Auditor, why it lives on the room rather than the account or the lineage, and why `agents/fencing.py` now exists. Read before touching `sessions.audience`, `TurnContext.audience`, or anything that lets user text reach a prompt. |
| Custom archetypes | `docs/custom-archetypes.md` | Resolved design for #65 — what a user may author and what stays ours. Domains come from the shipped vocabulary because they are the Auditor's routing key; the one free-text field is fenced as data and `attack_strategy` is composed by us; every room seats at least one shipped archetype, because `openers` and `nudges` are hand-written and a room of custom panelists opens in silence and reaps with no warning. Read before touching `agents/composition.py`, `by_name`, or anything that lets user text reach a prompt. |
| Account deletion | `docs/account-deletion.md` | What deleting an account destroys, what it anonymises, and why the two differ. Read before touching `accounts`, `ledger_entries`, the cost telemetry, or anything that adds a table carrying `user_id` — nothing cascades from a *user* by design, so a table left out of the deletion path is personal data retained forever with nothing raising. |
| Reconnect | `docs/reconnect.md` | Resolved design for #100 — the reconnect window and the zero-audio refund. Why disconnected-with-hope is a `disconnected_at` stamp on a still-`active` session rather than a sixth state, why closing the interrogation span is what suspends billing, caps and idle in one stroke, the connection nonce that stops a stale socket settling a resumed room, and why the window is never called "grace". Read before touching the relay's `_end`, the meter's `_live_rooms`, the reaper's ACTIVE paths, or anything that opens or closes a `SessionPhaseSpan`. |
| Cost reconciliation | `docs/cost-reconciliation.md` | The procedure for #14 and Open Risk #4 — the SQL for our side, what to pull from each vendor for the same window, and what the comparison decides. Two of its three questions need no invoice at all, including the observed debrief median that `CLAUDE.md` parks the 20-minute soft cap on. Read before changing a rate in `agents/../voice/rates.py`, and before any price in `Product.md` §4.4 moves. |
| Demo video | `docs/demo-video.md` | The two-minute demo video (§7 week 8): seeding minutes and a lineage, staging the contradiction the video exists to show, the shot list with voiceover, and the audio trap. The live room plays panel speech on the voice-call path, which a screen recorder may not capture, so test before shooting. Read before recording any promotional footage of the app. |
| Brand and voice | `docs/brand-voice.md` | The outward brief — positioning, voice, vocabulary, the palette and type that carry outward, and the hard rules on what may never be published (no prices, no invented users or metrics, no delivery-scoring claim, no logo). Self-contained so it can be pasted into a content tool, which `design-guide/` must never be: those mockups are stale and their imagery is unlicensed. Read before writing any social post, landing copy, store listing or ad. |
| Analytics | `docs/analytics.md` | Resolved design for #105 — first-party events in our own Postgres, viewed with SQL in the Supabase dashboard. Why an event is a name, a user and the server's clock with no properties column, why the funnel stays in the domain tables, the twelve-month sweep, and the ready-made retention queries. Read before adding an event name, a property, or any analytics dependency. |
| Design Guide | `design-guide/pitchgo_design_system/DESIGN.md` | Design tokens (colors, type, spacing, shape, elevation) — source of truth for `impeccable` skill. |
| Screen mockups | `design-guide/<screen>/code.html` + `screen.png` | **Stale — layout/density reference only.** Predate the rename (PitchGo/PitchForge) and encode retired decisions: token counters, `investment_verdict_dashboard`, "Avg. Likelihood %", pitch-only copy. See `Product.md` §9 → Brand Commitments. |

---

## Tech Stack

| Layer | Technology | Function |
| --- | --- | --- |
| Frontend | Expo / React Native | iOS + Android; native mic control, audio streaming |
| Backend API | FastAPI (Python) | Async endpoints, extraction, ledger, streaming webhooks |
| Orchestration | LangGraph / PydanticAI | Agent state machine, panel turn-taking, Auditor workflow |
| Voice | ElevenLabs Agents (primary), Gemini Live (fallback) | Bidirectional streaming, barge-in, distinct per-archetype voices |
| Ledger DB | Supabase (PostgreSQL) | Minutes/token decrements under strict RLS |
| Billing | RevenueCat | Subscriptions, entitlements, paywalls |
| Document parsing | PDF/PPTX extraction + vision model for slide photos | Per-slide claim and figure storage |

**Decision: ElevenLabs for voice**, chosen for native barge-in and distinct per-archetype voice identity — not TTS alone. Keep the voice layer behind an interface so Gemini Live (or another provider) can be swapped in if latency or cost fails to hold. Two things to verify early, every time voice logic changes:

1. Latency under concurrent multi-agent load (target: hold the illusion under ~1.5s; above it, the room feels fake).
2. Cost per minute at real concurrency — confirm against actual provider invoices, not list-rate assumptions.

**Removed/rejected integrations — do not reintroduce without explicit human approval:**
- Dynamic social-profile scraping of real people (LinkedIn/X) for panelists — right-of-publicity, ToS, GDPR exposure. Panelists are pre-built archetypes; user-supplied free-text context is the only permitted enrichment.
- Direct Google Drive OAuth — restricted scopes, slow verification, 100-user cap while unverified. Use the native OS file picker (iOS Files / Android SAF) instead.
- Exa.ai / Firecrawl profile scraping — removed alongside the social-profile feature.

---

## Repository Layout (target — build toward this)

```
flintroom/
├── app/                # Expo / React Native app
│   └── src/            # SDK 57 template convention — do not fight it
│       ├── app/        # Expo Router route tree — the router owns this directory
│       ├── components/
│       │   ├── ui/     # Primitive, reusable, no business logic
│       │   └── modules/ # Feature-specific (panel setup, live session, debrief, sparring)
│       └── lib/        # API client, audio streaming, auth
├── backend/            # FastAPI + LangGraph/PydanticAI
│   └── app/
│       ├── modules/    # panels | sessions | auditor | debrief | billing | ingestion
│       ├── core/        # config, database, security, dependencies
│       ├── shared/       # base models and schemas
│       └── agents/       # panelist archetypes, Auditor, coach — persona + strategy + grounding
├── contracts/
│   └── openapi.yaml     # API contract — frontend types generated from this
├── design-guide/         # Design tokens + per-screen HTML/PNG reference (existing)
└── Product.md             # Source-of-truth product spec (existing)
```

Never put business logic in route handlers. Never do DB queries at the route layer — keep it thin: parse request → call service → return response.

---

## Security & Privacy First — Core Development Principle

**Every implementation decision starts with security and privacy.** This is an always-listening, mic-access AI app — App Store review will scrutinize recording retention and data handling (see Open Risks). Before writing any feature, ask:

1. Who can call this endpoint? → RBAC/auth dependency applied before service logic.
2. What audio/text is captured, and for how long? → Retention policy must be explicit, not implicit.
3. What data is exposed in responses? → Minimum necessary fields only.
4. Can this be abused? → Rate limiting, input validation, idempotency considered.
5. What happens if it fails mid-session? → Minutes must never be silently over-charged; see Metering Rules.
6. Is this logged? → Security- and cost-relevant actions (session start/end, minute decrement, top-up purchase, refund) always audited.

### Mandatory rules on every feature

| Concern | Rule |
| --- | --- |
| Input validation | Pydantic schema on every request body. No raw dict access. |
| Auth | JWT/session verified via dependency before any handler runs. |
| RBAC | Role/entitlement checked via dependency, never inside service or model. |
| File access | Uploaded material (PDF/PPTX/photos) delivered via presigned URL only, never proxied. |
| Money + minutes | All ledger state changes inside DB transactions, decremented as consumed (not reserved upfront). Never modify the ledger outside explicit service methods. |
| Webhooks | Signature verified (RevenueCat, ElevenLabs if applicable) before payload parsed. Unverified = reject + audit log. |
| Secrets | Zero secrets in code or logs. `.env` local only, gitignored. |
| Recordings/PII | No raw audio or full transcript returned in list endpoints. Retention window explicit and documented before any recording feature ships. |
| Audit trail | Money movements are recorded in `ledger_entries` (never duplicated elsewhere); everything else worth proving goes to `audit_events`. See Audit Model below. |
| Rate limiting | Auth and session-start endpoints rate-limited. |

When in doubt: **deny by default, log the denial, surface to human if ambiguous.**

---

## Architecture Decisions (locked)

Do not re-open without explicit human instruction.

| Decision | Choice | Reason |
| --- | --- | --- |
| Panel identity | Pre-built archetypes only, no real-person scraping | Legal exposure + unnecessary — training value lives in archetype and thesis, not identity |
| Material ingestion | Native OS file picker (not Drive OAuth) | Same user outcome, zero integration/verification cost |
| Metering boundary | Only live interrogation is metered; debrief + sparring are unmetered (§4.1 of `Product.md`) | Meters only the actual cost driver; psychologically inverted in the user's favour; removes the "abandoned re-try" failure mode |
| Voice provider | ElevenLabs Agents, Gemini Live as fallback behind an interface | Native barge-in, distinct per-archetype voices; swappable if cost/latency fails |
| Panel internals | Persona + attack strategy + grounding context, as config not code | Makes new archetypes and the v2 professional-conversation expansion configuration work, not a rewrite |
| Backend coupling | No mobile-only assumptions (device-coupled auth, push-token dependencies, phone-specific audio formats) | Keeps a future web client possible without a backend rewrite |
| Supabase scope | **Managed Postgres + RLS only.** Not Supabase Auth, Storage, PostgREST, Realtime, or Edge Functions without explicit approval | Keeps a move to RDS/Cloud SQL a `pg_dump` and a connection string rather than a rewrite. The app already holds no Supabase credentials — all access is through FastAPI — so the lock-in surface is near zero and worth keeping that way. See Database Portability below |
| Allowance unit | Minutes, monthly, no roll-over reset weekly | Rehearsal is bursty; weekly reset punishes exactly the usage pattern the product serves |
| Video/body-language analysis | Deferred, not planned for v1 | Commodity layer, expensive, scientifically contested signal — audio-only serves the adversarial thesis |

---

## Metering Rules (Non-Negotiable) — §4 of `Product.md`

Flintroom sells **minutes of live interrogation**. Everything after is unmetered. Get this wrong and either margin collapses or the product's core promise (unlimited teaching) breaks.

| Phase | Metered? |
| --- | --- |
| Live interrogation (multi-agent panel, barge-in, background Auditor) | Yes |
| Voice debrief (single coach voice, turn-based) | No |
| Sparring re-tries | No |

Rules that follow from this, enforced in code, not just UI copy:

- Minutes are **decremented as consumed**, never reserved upfront, and **refunded automatically on technical failure**.
- **Never interrupt a live session** to show a paywall. If a user runs out mid-interrogation, let the panel finish, then settle and hand off to debrief.
- Idle/silence detection ends abandoned sessions and refunds automatically.
- Soft cap (~20 min) on unmetered coaching, with a friendly extend prompt. **The rule stands; its reason changed on 2026-08-18.** It was written as a cost circuit breaker against an idle open session, and turn-based coaching (`docs/debrief-and-sparring.md` decision 5) removed that cost entirely — with no socket there is no stream, and an untouched debrief bills nothing. What the cap protects now is the *promise*: "unlimited coaching" stays credible only if an abandoned tab is not counted as a session. Measured rather than assumed — `session_costs.debrief_seconds` is written from the coaching turns themselves, and §4.3 wants the observed median before the 20 is defended.
- Per-account daily spend ceiling as a runaway-cost circuit breaker.
- Top-up minutes never expire; monthly allowance is consumed before top-up balance.
- Never display a depleting counter ("2 of 5 credits left"). Show remaining minutes plainly, framed generously.
- On a second top-up within a rolling 30-day window, the upgrade becomes the default option, not the top-up — see the Credit-Toward-Upgrade Rule in `Product.md` §4.5. Never gate a top-up behind the upgrade prompt.

**Cost instrumentation is a required task, not a nice-to-have.** Every price in `Product.md` §4.4–4.5 is derived from unverified vendor list-rate assumptions. Build the `session_costs` telemetry table (see `Product.md` §4.3 for exact schema) into the pipeline from the *first working voice loop* — not as a later addition. Do not let pricing ship or change without observed-cost reconciliation against provider invoices (target: within 10%).

---

## Backend Code Standards (FastAPI)

### Module structure

```
backend/app/modules/{module}/
├── router.py          # Thin: parse request → call service → return response
├── service.py         # Business logic, task dispatch
├── models.py          # SQLAlchemy async ORM models
├── schemas.py         # Pydantic v2 request/response schemas
└── dependencies.py    # Module-specific FastAPI dependencies (if needed)
```

### DB access

- All DB operations via SQLAlchemy async sessions, injected via `db: AsyncSession = Depends(get_db)`.
- Never use raw SQL unless a complex query justifies it — prefer the ORM.
- Every write touching multiple tables (especially the minutes ledger) uses a transaction: `async with db.begin()`.
- Balances and any other read-modify-write on money take `SELECT ... FOR UPDATE` on the owning row. Contention is per account and a user may hold only one active session, so this serializes a user against themselves and never against another user — which is also what keeps the write path shardable by `user_id`. Do not introduce a global counter, a shared lock, or a cross-user aggregate on the write path; see `docs/deferred-scale-work.md`.

### Database portability (follows from the locked Supabase-scope decision)

Supabase is the Postgres host, not the application platform. These are the rules that keep the exit cheap — each is free to follow now and expensive to retrofit:

- **All DB access goes through FastAPI.** No `supabase-js`, PostgREST, or direct client credentials — the mobile app never holds a database key.
- **`user_id` is a plain UUID.** Never a foreign key to `auth.users`. This is the single decision that separates a weekend migration from a quarter-long one.
- **RLS policies are written deny-all, without `auth.uid()`.** Service-role access through the API is the real wall; RLS is defense-in-depth, and policies free of Supabase auth helpers run unchanged on any Postgres.
- **Auth provider sits behind an interface**, decided on its own merits — not inherited because the database happens to be Supabase.
- **Object storage sits behind an interface**, same pattern as the voice provider. The contract is the presigned URL, not the vendor SDK.
- **No Supabase-specific SQL.** Standard extensions available on RDS/Cloud SQL (e.g. `pgvector`) are fine; Supabase-only helper schemas are not.

### Types

`uvx ty@0.0.73 check app` runs clean, and that is the only state it is worth
keeping in — sixty-eight known diagnostics meant a sixty-ninth was invisible.
Run it before committing backend work; it is fast and needs no environment.

**The version is pinned in `pyproject.toml` on purpose.** `ty` is preview-stage,
so an unpinned run can report differently on unchanged code, and "the checker is
clean" would become a statement about the day rather than about the source.

**There is no suppression comment anywhere in `app/`.** Every diagnostic so far
had a real fix — an annotation that was wrong, a null nobody guarded, a library
gap worth naming once in a helper. If a suppression ever becomes the right
answer, it carries the reason beside it; a bare ignore outlives the thing it
suppressed.

`.github/workflows/ci.yml` runs it on every push, at the pinned version, beside
`pytest`. It is a required check rather than a habit.

### Schemas

- All API inputs validated with Pydantic v2. No raw dicts at the router level.
- Response models always explicit — never return ORM objects directly. Use `model_config = ConfigDict(from_attributes=True)`.

### Logging and error handling

**Errors.** Services raise typed errors from `app/core/errors.py`; routers never translate them. One handler in `app/main.py` turns them into responses, so the status code for a given failure is decided once.

- `message` + `code` go to the client. `context` goes to the log only — echoing it leaks internal identifiers to whoever is probing the endpoint.
- Never raise bare `Exception`, and never catch broadly enough to swallow one. An unexpected exception stays a 500 with a logged traceback and a generic body; dressing a bug up as a tidy 4xx is how a crash becomes invisible.
- Provider failures surface as `ProviderUnavailable` (502) and **must not name the vendor** to the client — it exposes internal architecture and goes stale the moment the voice provider is swapped, which the stack is built to allow.

**Logging** via `app/core/logging.py` — `get_logger(__name__, tag="billing")`.

- Context is keyword arguments, never f-strings: `log.info("tick_charged", session_id=..., seconds=15)`. Identifiers must be greppable and named identically on every line that carries them.
- Tag names the subsystem — `billing`, `sessions`, `voice`, `auditor`, `http` — so one live session can be followed across modules.
- **Never log raw audio, transcripts, or ingested material contents.** Sensitive-looking keys are redacted automatically, but transcript text is not detectable by key name and must not be passed at all.
- Log every money movement (tick, refund, grant, forgiveness, period reset). These are the lines that answer "why is this user's balance what it is."
- Application logs are **not** the audit trail. The audit trail is a database table and may not be sampled or dropped.
- `configure_logging()` belongs at process startup (the app lifespan), never in the app factory — it replaces root handlers, and a factory that does that by being called will fight anything else with an opinion about handlers.

### Audit model

Two tables, one rule: **a balance change is recorded exactly once.**

- **`ledger_entries` is the money record.** Every tick, grant, refund, expiry and forgiveness, append-only, each row carrying `actor` / `actor_id` / `request_id` and `balance_after_seconds`. Never mirror a money movement into `audit_events` — a second copy of a balance can silently disagree with the first, and the reconciliation test only guards the ledger.
- **`audit_events` is everything else worth proving:** session start/settle/reap, denied starts, entitlement changes, rejected webhooks, permission denials, admin overrides. No foreign keys — an audit row must survive deletion of whatever it describes.
- **Provenance is set at service construction**, not per call: `LedgerService(db, actor=ActorContext(...))`. A caller cannot then attribute half its writes to one actor and half to another. Defaults to `SYSTEM`; `ADMIN` requires an `actor_id`.
- **Audit context is redacted like a log line.** These rows are append-only, so a secret written into one cannot be edited back out.
- **`AdminService` is read-only.** Anything an operator changes goes through the owning service so it lands with an `ADMIN` actor attached — a support tool that writes directly is how an unexplained balance appears.

> **Naming:** the module is `audit_log`, never `auditor`. **Auditor** is the domain term for the background agent that cross-checks a live transcript against ingested material (see Domain Language). Colliding the two makes every future search for either useless.

### Error status codes

- Business rule violations → `HTTPException(422)`. Auth failures → `401`/`403`. Not found → `404`.
- Never raise bare `Exception`. Never swallow exceptions silently — log, then re-raise or return a typed error.
- External service failures (ElevenLabs, RevenueCat, Supabase, document extraction) → catch specific SDK exceptions, log with full context, raise `HTTPException(502)`.
- Handle the unhappy path before the happy path: validate inputs, check preconditions (entitlement, remaining minutes), then execute.

### Edge cases every feature must explicitly handle

| Edge case | Required handling |
| --- | --- |
| Unauthenticated request | 401 |
| Insufficient entitlement / role | 403, logged with user_id + attempted action |
| Resource not found | 404, no logging needed |
| Duplicate action (idempotency) | 200/409 depending on context — never 500 |
| Malformed input | 422 via Pydantic, automatic |
| Out of minutes mid-session | Never hard-cut; finish current panel turn, hand off to debrief (see Metering Rules) |
| External voice/LLM provider timeout | Retry with backoff; if unrecoverable mid-session, degrade gracefully and refund the affected minutes |
| Webhook invalid signature | 400 + audit log, payload never processed |
| File too large / wrong type | 413 / 415, validated before upload attempt |
| Concurrent write conflict on ledger | DB transaction rollback + 409 |

### Migrations

- Every schema change = new migration. No manual DB edits.
- All migrations backwards-compatible with the previously deployed version.

---

## Agent/Panel Architecture

- Build panelists internally as **persona + attack strategy + grounding context** — never hardcode a named individual or scrape one. New archetypes are configuration.
- **Targeted interruption**: the Auditor detects a mismatch between spoken claim and ingested material; the archetype whose domain covers that metric interrupts (CFO archetype catches margin contradictions, not the Technical Skeptic).
- **Panel composition should default to mixed**, not uniformly hostile — ship a champion, a skeptic, and a neutral by default.
- Every challenge should trace back to something the user said or attached — ungrounded generic questions are the primary retention killer (Open Risk #2). Do not ship interrogation logic that can't cite its source.
- Difficulty calibration escalates across sessions — a first session that destroys the user produces churn, not resilience.
- **The coach converses freely but is grounded only in the session.** Debrief and sparring are genuine conversation — follow-ups, clarifications, the coach pushing back on a weak re-answer (§3.5: "a conversational debrief, not a static dashboard"). Do not reduce it to a rigid form-filling flow. What is bounded is the coach's **grounding scope**: the session transcript, ranked weak answers, Auditor findings, and ingested material. The coach does not evaluate fresh material it was never handed — that is an interrogation, and interrogation is metered.
- **Enforce that scope structurally, not with a system prompt.** A prompt saying "don't do general pitch review" is one jailbreak from failing, and users will try. Constrain it in the orchestration graph: coaching turns carry the session's artifacts as their grounding context and nothing else, and a request to evaluate new material is classified and redirected to starting a session. The redirect is a product moment ("that's what the room is for"), never a paywall — see Metering Rules.
- **Why this is a hard constraint:** an unscoped coach hands every user unlimited free pitch review and removes the reason to pay for the panel, and open-ended "listen and tell me how I did" is exactly the competitor product the wedge exists to refuse (`Product.md` §1). Scoping is also what keeps the unmetered promise honest — the bound is subject matter, not a clock, so "unlimited coaching" stays literally true.

---

## Frontend Code Standards (Expo / React Native)

- The live interrogation screen is hands-free by design: the phone sits on the desk. Do not add UI that assumes the user is looking at or holding the phone during a session — active-speaker indicator and room-temperature gauge are secondary/glanceable only.
- Use the design tokens in `design-guide/pitchgo_design_system/DESIGN.md` (colors, type scale, spacing, radius, elevation) as source of truth — do not invent new values. The per-screen `code.html` files are a *stale* content model (tokens counter, investment verdict, PitchGo naming): read them for layout and density, never reproduce their content. See `Product.md` §9.
- Platform is **iOS-led with one shared design language across iOS and Android** (`Product.md` §9 → Platform). Follow Apple HIG for structure, navigation, and interaction — safe areas, tab bar for top-level sections, live edge-swipe back, 44×44pt targets, Dynamic Type, Dark Mode as a first-class appearance. Brand expresses through tint, type, motion, and content, not through reinvented controls.
- Accessibility floor is **WCAG 2.2 AA plus live captions** for panel speech — a voice-only interrogation is unusable without them, and it is a v1 requirement, not a post-launch addition.
- "Room temperature" and similar scale language must stay neutral and transferable across contexts (e.g. "Convinced / Skeptical / Losing the room") — never reintroduce the retired "Investable → Delusional" framing; it doesn't work outside a pitch context and this product is not pitch-only.
- Never display a depleting-credits counter (see Metering Rules).
- `components/ui/` — primitive, reusable, no business logic. `components/modules/` — feature-specific, may call the API, tied to one module.
- No God components. If a file exceeds ~200 lines, split it.
- API calls via a client generated from `contracts/openapi.yaml`. Never hardcode API paths in components. Regenerate with `npm run generate:api`; the generated `src/lib/api/schema.d.ts` is committed, so a clone builds without running codegen. The generator runs through a pinned `npx` rather than sitting in `devDependencies` — it peers on TypeScript 5 while the SDK ships TypeScript 6, and a build-time CLI has no reason to share the app's compiler version. Do not "fix" this with `--legacy-peer-deps`.
- **The audio layer is owned (#25).** Live capture and playback run on `app/modules/room-audio`, our own Expo native module; saved-room and coach-line file playback runs on `expo-audio`. Which profile a screen opens — the AEC pair for the live room, a plain microphone for the debrief — is decided in exactly one place, `app/src/lib/voice/stack.ts`. Do not reintroduce a third audio stack, and do not open a stream outside `stack.ts`. See `docs/echo-cancellation.md` → "The owned stack, measured".

---

## Test-Driven Development — Mandatory

No feature ships without tests. Loop: write failing test → minimum code to pass → refactor, keeping tests green. Invoke the `tdd` skill before any feature work — see `.agents/skills/tdd/` for interface design, mocking, and refactoring guidance specific to this workflow.

**Backend:** `pytest` + `pytest-asyncio` + `httpx.AsyncClient` for endpoint tests, `factory_boy` for fixtures, `freezegun` for time-dependent tests (session timeouts, minute expiry).

**Frontend:** `jest-expo` + `@testing-library/react-native` for components, `maestro` for E2E, `msw` for API mocking. Pure logic — PCM conversion, the connect sequence, close-code routing — is plain TypeScript and needs no renderer, but it runs on the same runner: `@testing-library/react` renders through `react-dom`, which React Native does not have, and a second runner would be a second config, a second mocking story and a rule about which to use.

### Critical flows that need E2E coverage before any release

- Panel setup → attach material → live interrogation → session ends within allowance.
- Live interrogation → runs out of minutes mid-session → graceful handoff to debrief (never a hard cutoff).
- Debrief → sparring re-try → prep sheet export.
- Top-up purchase mid-flow → credit-toward-upgrade prompt on second top-up.
- Auditor flags a contradiction → correct archetype interrupts (grounding correctness, not just UI).

---

## Build Sequence

Follow `Product.md` §7 phase order — do not reorder or start a later phase before the current phase's tests are green:

1. **Weeks 1–2 — Foundations:** Supabase schema + ledger with RLS, FastAPI scaffold, document extraction, RevenueCat wired early.
2. **Weeks 3–4 — The Voice Loop:** ElevenLabs Agents channel, bidirectional streaming from Expo, barge-in verified end-to-end. Ship the `session_costs` telemetry table alongside this — not after.
3. **Weeks 5–6 — Panel and Auditor:** LangGraph orchestration, turn-taking, inter-panelist disagreement, grounded challenge generation, difficulty calibration.
4. **Week 7 — Debrief and Sparring:** coach walkthrough, ranked weak answers, re-try loop, exportable prep sheet.
5. **Week 8 — Polish, Store, Demo:** onboarding, privacy policy / recording-retention documentation, App Store review with a week of slack, demo video.

Backend endpoints always precede frontend for the same feature. Within a feature: implement backend → update `contracts/openapi.yaml` → regenerate frontend client → build UI.

---

## Open Risks (flag proactively when relevant work comes up)

1. **Do people tolerate being attacked?** Riskiest product assumption — validate with real users, don't just assume the engine is right because it's built.
2. **Grounding quality.** Ungrounded generic questions kill retention faster than any UI flaw — treat this as a correctness bar for the Auditor/panel work, not a nice-to-have.
3. **Voice latency.** Above ~1.5s the illusion breaks. Measure on every change to the voice pipeline.
4. **Unit economics.** Every tier margin in `Product.md` §4.4 depends on the unverified $0.12/min interrogation assumption. Do not let pricing changes ship without the cost-instrumentation task (§4.3) backing them.
5. **Store review.** Mic-access AI apps draw scrutiny — privacy policy and recording-retention answers must be ready before submission, not written the week of.
6. **Scope creep.** Presentations only for v1. Professional-conversation expansion (interviews, negotiations, difficult conversations) is post-launch, justified by usage data — do not build toward it speculatively even though the architecture supports it.

---

## Domain Language (use exactly)

| Term | Meaning |
| --- | --- |
| **Panel** | The assembled set of AI archetypes interrogating the user in a session |
| **Archetype** | A pre-built panelist persona (e.g. Growth Maximalist, Margin-Obsessed CFO) — never a real scraped person |
| **Auditor** | Background agent that cross-checks the live transcript against ingested material for contradictions/unsupported claims |
| **Interrogation** | The live, metered, hands-free Q&A phase |
| **Debrief** | The unmetered post-session coach walkthrough |
| **Sparring** | Unmetered re-try loop where the user re-answers a fumbled question until it holds |
| **Room temperature** | The directional live-UI read on how the panel is receiving the argument (neutral scale, never "Investable → Delusional") |
| **Minutes / Time Under Fire** | The metered unit — interrogation time only, not debrief/sparring |
| **Grounded challenge** | A panel question that traces back to something the user said or attached, as opposed to a generic hard question |

Never abbreviate these. Never invent synonyms. Consistency = searchability.

---

## What the Agent Cannot Do

- Deploy to app stores, Supabase prod, or any hosting target directly.
- Change the confirmed tech stack (Expo, FastAPI, LangGraph/PydanticAI, ElevenLabs, Supabase, RevenueCat) without explicit human approval.
- Make product decisions — scope, pricing, tier structure, audience prioritization is human's call.
- Reintroduce social-profile scraping, Drive OAuth, or video/body-language analysis without explicit instruction (see Architecture Decisions).
- Change the metering boundary (what's metered vs. unmetered) without explicit instruction — this is a core trust mechanic, not a tuning knob.
- Ship or change pricing without the cost-instrumentation task (`Product.md` §4.3) backing the numbers.
- Write migrations that drop columns or tables without human review.
- Add dependencies without justifying the addition (what it replaces, why it's needed).
