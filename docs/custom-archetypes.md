# Custom archetypes

**Resolved design for #65 — a panelist a user writes, seated in a room beside
the eight the product ships.**

Decided 2026-08-20 by grilling the requirements against the code rather than
against the mockup, because the code turned out to have anticipated most of
this and the mockup had gone stale in a way that matters.

`design-guide/create_custom_panelist/` asks for Panelist Name, Core Focus,
**Investment Stage**, Feedback Tone and Detailed Persona Instructions, with
placeholders reading `e.g. The Skeptical VC` and *"this AI investor should lean
on during the pitch review"*. That is the retired pitch-only product
(`Product.md` §9 → Brand Commitments). Its **layout and density** are still
reference; none of its fields survive as written.

Three things in the codebase were written in advance of this feature and are
inherited rather than re-decided:

- `agents/archetypes.py` — `cadence` is nullable *"only for a custom archetype,
  which a user writes without one"*, so the system supplies it.
- **Voice is auto-assigned by default, with an optional override from the same
  eight.** `docs/panel-orchestration.md:436` settled this on 2026-08-16 and the
  reasoning is worth keeping: *"Decided rather than defaulted: most users
  writing a custom archetype care about the argument it makes, not its timbre,
  and making them cast it is a decision tax on the feature's main path."*

  So the form carries a voice picker that is **optional and defaulted**, never a
  required field — the eight, plus "pick one for me", which is what an untouched
  form does.

  `voices.py` is built for exactly this. Voices are *characters* rather than
  people — `MEASURED` describes how somebody sounds, so *"a custom archetype can
  be cast in it without inheriting anything about the shipped archetype that
  happens to share it"* — and `CASTABLE` is deliberately one set: *"a custom
  archetype chooses from exactly what the shipped ones use, so nothing about a
  user's room sounds second-class."* That vocabulary was written to be shown to
  a user.

  **The uniqueness constraint is per-room, not per-library.** Two custom
  archetypes may share a voice safely if never seated together, so the check
  belongs in `assemble()` beside the tier cap — not in a database constraint,
  which would forbid a legal arrangement. Eight voices against eight shipped
  archetypes means a seated custom panelist always finds a free one, and an
  override that collides with a seated panelist falls back to auto rather than
  refusing the room.
- `agents/opening.py:173` — *"An archetype with no openers is skipped rather
  than fatal. Custom archetypes are rows a user typed and carry none."* A custom
  panelist never holds the floor first, and that is settled.
- `agents/composition.py` — `compose()` takes `audience`, `role` and `seats`,
  no `user_id` and no database, resolving through constants. **Automatic seating
  is structurally incapable of picking a custom archetype**, and it runs at
  sign-up before one could exist. Custom archetypes are manual-only by
  construction, not by rule.

That last one bounds the whole feature: something loads a row, builds an
`Archetype` from it, and the composer, the opener and the Auditor never learn
the difference. **`Archetype` is the boundary.**

---

## 1. Domains are chosen from the shipped list, never typed

`domains` is not descriptive metadata. It is the routing key for §3.3 targeted
interruption — `docs/auditor-grounding.md` has each derivation pack declare
which domain owns a figure, and `archetypes.py` is the other end of that
lookup. **An archetype with empty `domains` can never be the panelist the
Auditor interrupts with.** It would still take ordinary turns, and it would be
structurally incapable of the product's signature moment.

The mockup's free-text "Core Focus" produces a string, not a domain key, so it
routes nothing.

So the form offers the shipped domain vocabulary as a multi-select, and there
is no free-text domain field anywhere.

**Why not map free text onto domains with a model.** That is a classifier
deciding who interrupts, and `docs/debrief-and-sparring.md` keeps judgements —
as opposed to extractions — out of the graph on purpose.

**Why a closed list is the safe one.** On 2026-08-20 a collision test found that
`retention` was claimed by both the Customer Advocate and the Risk Officer, and
the Risk Officer's `data` domain **silently never fired** because the Advocate
listed the word first. A user-authored domain shadows a shipped one the same
way and nothing reports it. A closed vocabulary makes that impossible rather
than catchable.

**The cost, stated:** somebody who wants a panelist obsessed with something the
vocabulary has no word for gets the nearest neighbour. The ambition can live in
the persona field, where being vague costs nothing.

## 2. One short free-text field, fenced as data — and we write the attack

The user writes **who this person is**, capped far shorter than the model's
2000 characters. We compose `attack_strategy` from the domains they picked.
They author character; the line of attack stays ours.

The composer prompt (`agents/panel_models/gemini.py:255`) interpolates persona
and strategy first and puts the hard prohibitions last, which is the right
order and is kept. The user's text is fenced inside an explicit delimiter and
labelled as a description supplied by the presenter, so it reads as data rather
than as instructions.

**Why fencing rather than trust.** `CLAUDE.md` states the principle about the
coach: *"Enforce that scope structurally, not with a system prompt. A prompt
saying 'don't do general pitch review' is one jailbreak from failing, and users
will try."*

**Why fencing rather than no free text at all.** A custom panelist whose
character comes entirely from dropdowns is the eight shipped archetypes wearing
a different hat, and there would be no reason to build the feature.

**Why `attack_strategy` is not handed over.** It is the field that decides what
the panel *does*. Handing it over hands over the grounding rules, which is the
one thing this product cannot afford to lose — Open Risk #2 calls ungrounded
questions the primary retention killer.

**The threat model is unusual and worth naming.** The user is authoring a
panelist to interrogate *themselves*; nobody else is attacked. The risks are
therefore not abuse of a third party but (a) defeating the grounding rules so
the panel invents figures, and (b) producing content that is synthesised to
audio and stored in a recording on our infrastructure, which is App Store
review surface.

**Fencing raises the bar; it does not seal the door.** #63 — *"The CFO ignores
a hard prohibition the other archetypes obey"* — is a first-party, hand-tuned
persona already defeating one of those NEVER rules with the rule correctly
placed last. **#63 should be closed before this ships.** Shipping
user-authored personas on top of an unexplained first-party one is stacking.

## 3. At least one shipped archetype is seated in every room

Enforced at **composition**, not at start: the setup screen will not let the
last shipped panelist be removed while a custom one is seated, and the server
refuses the same shape with a typed error.

Two things break in a room seated entirely from custom archetypes, and one of
them breaks silently:

- **It opens in silence.** `opening.NoOneToOpen` exists for exactly this and
  says so — *"reachable only by a room seated entirely from custom
  archetypes"*. It is raised rather than returning `None` so a room cannot
  quietly open in silence, but it is an exception at session start, not
  something a user can act on.
- **Nobody warns them at sixty seconds.** `nudges` is the same shape as
  `openers` — hand-written, per archetype — and is what the room says before
  the ninety-second idle timeout reaps and refunds (#24). A room with nobody to
  say it reaps with no warning, and the person it exists for *"has stopped
  looking at the phone"*.

**Why composition and not `start`.** A refusal at Start is a paywall-shaped
moment on a screen the user has already committed to, and the metering rules
are explicit that a room in progress is never where a constraint is discovered.
Better that it is not an arrangement the picker will build.

**Why not give custom archetypes generic openers and nudges.** Both are
hand-written deliberately, and `nudges` more strictly: identical every time so
it is recognisable rather than parsed, and in character because *"every voice in
this room belongs to somebody at the table"*. A generic line breaks the one
moment the panel is not interrogating.

## 4. Immutable once seated; delete is an archive

`SessionPanelist` stores **a name, not a snapshot**, and its own docstring names
this feature as the moment to revisit that: *"it is the decision to revisit when
Pro users start authoring their own — at which point a panelist may point at a
row rather than a constant, and the question becomes what happens when its
author deletes it."*

- Editing a custom archetype that has **never been seated** mutates the row.
- Editing one that **has** writes a new row and retires the old, so the name in
  `session_panelists` keeps pointing at the text that was actually in the room.
- "Delete" sets `archived_at`. It leaves the picker and stops being seatable,
  and stays readable for every room that used it.

This keeps the existing decision intact rather than overturning it: the name
still resolves, it just resolves to something that cannot change underneath it.
Rooms are kept for the life of the account (`docs/session-retention.md`), and
the Library, Progress, the transcript and the debrief all render who was there.

**Editing is the worse hazard, and the quieter one.** Renaming a panelist from
"The Board Chair" to "Angry Investor" would make every past room retroactively
claim a person who was never in it, with nothing erroring.

**Two obligations this creates.**

- **A user who "deletes" a panelist has not deleted their data.** The control
  must say *remove from your panel*, never *delete*, and
  `docs/privacy-policy.md` must say what actually happens. Account deletion
  (#53) destroys the rows outright — that is the real delete, and this table
  must be added to that path. `docs/account-deletion.md`: nothing cascades from
  a user by design, so a table left out is personal data retained forever with
  nothing raising.
- **Any per-account cap counts live panelists, not rows**, or editing a
  well-used one repeatedly walks somebody into a limit they cannot see.

**The alternative, rejected:** snapshotting persona onto `session_panelists` at
seating. It works, and it is the thing `models.py` explicitly declined —
every row carrying two kilobytes of prose that is identical across every
session ever run. Worth revisiting only if a room should be a photograph rather
than a reference.

## 5. The stored name is `custom:{uuid}`; the user supplies a title

Never user-supplied. `by_name()` refuses any name carrying the prefix and
raises rather than returning `None`, so a lookup cannot quietly cross
authorities; a separate loader owns the prefixed ones.

The user supplies a **title** — "The Board Chair" — which is what they and the
transcript see, and which may be anything, duplicated, or identical to a
shipped title without consequence.

**Why.** `SessionPanelist` stores a name and `by_name()` resolves it against
the shipped library. A second authority makes one namespace with two writers,
and a panelist stored as `cfo` resolves a past room to the wrong person with
nothing erroring.

This is the third occurrence of that shape in one day: the `retention`
collision above, and `vocabulary.ts` mapping `distracted` while the server
shipped `distracted_executive` — where `panelistName` falls back to the raw key,
so the Library was one seating away from displaying the literal string
`distracted_executive`. Both were namespaces with no guard. A prefix makes
collision impossible by construction rather than catchable by validation.

It also carries the versioning in §4: a new row on edit gets a new `custom:`
name, and old rooms keep pointing at the old one.

**The cost:** the identity cannot be renamed, only the title. Titles are what
anyone reads, so this is not a loss.

---

## Not decided, and deliberately

Both are the architect's and neither blocks the build:

- **A per-account cap.** Not a cost concern — a custom archetype costs nothing
  until seated, and seating is metered like any room. It is a picker that stops
  being usable somewhere north of a dozen. Counts live panelists, per §4.
- **Which tier this belongs to.** `ArchetypeCard.AuthorRow` already takes a
  `yours: boolean` plan flag, so the surface anticipates gating. Pricing and
  tier structure are `Product.md` §4.4–4.5 and are not the agent's to set.

## Build order

Backend first, per `CLAUDE.md`. Storage and the loader before any screen, so the
form is never a control that opens nothing — which is the reason `AuthorRow`
is drawn but deliberately not pressable today.

1. Close #63. It is the standing proof that persona text can beat a prohibition.
2. Table + migration, carrying `user_id` as a plain UUID, deny-all RLS, and a
   row in the account-deletion path in the same change.
3. The loader: row → `Archetype`, with the `custom:` prefix guard in `by_name`,
   and voice resolution — stored override if set and free, else first unused.
4. Composition refusal — the shipped-archetype floor, with its typed error.
5. `POST` / `PATCH` / archive endpoints, authenticated and rate-limited.
6. `contracts/openapi.yaml`, then regenerate the client.
7. The form, and only then make `AuthorRow` pressable.
