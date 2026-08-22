# Audience context

**Resolved design for #66 — the presenter's own sentence about the room they
are walking into, and the permitted substitute for the profile scraping this
project refused.**

Decided 2026-08-21 by grilling the requirements against the code. Four of the
five questions the task left open turned out to be already answered by decisions
the codebase had made for other reasons; only one was genuinely the architect's.

`Product.md` §3.1 removed dynamic social-profile scraping — right of publicity,
platform terms, GDPR — and named the replacement in the same breath:

> Permitted substitute: the user may paste their own text describing the
> audience ("my VP hates anything that adds headcount"), or paste a publicly
> published fund thesis, as free-text context. **User-supplied, not
> app-scraped.**

`CLAUDE.md` repeats it as the one permitted enrichment. It did not exist, and
`SessionStart` sets `extra="forbid"`, so a client sending it was refused rather
than ignored — the right failure, and still a failure.

**Why it is worth building rather than dropping.** It is the cheapest grounding
there is. Attaching a deck requires having one and waiting for extraction; one
sentence about the room requires neither, and it is the difference between a
generic CFO and one that knows headcount is the fight. Open Risk #2 is that
ungrounded generic questions kill retention faster than any UI flaw.

---

## 1. Shaped, never spoken — the architect's choice

**This was the only open product question, and `CLAUDE.md` reserves it:** *"never
guess on product behaviour — especially anything touching the interrogation
panel's tone."*

Somebody types *"my VP hates anything that adds headcount."* Two rooms come out
of that, and the difference is audible.

| | What happens |
| --- | --- |
| **Named** | *"Your VP hates headcount. So what happens when this needs three more?"* Unmistakably responsive, and it lands harder. |
| **Shaped** *(chosen)* | Nobody says the words. The CFO simply keeps returning to what this costs in people, and the presenter experiences a room that happens to press exactly where it hurts. |

Shaped, chosen 2026-08-21. The challenge still traces to something real — the
user is just not shown the wiring. Named, the first thing every user learns is
that the box is a puppet string, and the room stops being a room.

**The constraint is enforced, not hoped for.** `_SHAPED_NOT_SPOKEN` in
`agents/panel_models/gemini.py` says it in three clauses and
`tests/test_audience.py` holds each one, because both halves of the choice are
one edit apart.

**Its second sentence closes a hole in #45.** The persona forbids stating a
figure the presenter did not give — and a note *is* given. But it was never said
*in the room*, so the Auditor cannot check it and the debrief cannot rank an
answer to it. A figure lifted out of the box would be an invented one arriving
by the only door the NEVER rules leave open. Hence: *"Nothing in it is a fact
about their business that you may state."*

**It is ours to hold, not the presenter's to be reassured about.** The setup
screen briefly said *"It is never read out."* and the architect cut it on sight:
nobody typing into a text box expects it recited back, so the sentence answers a
question no user has — and reading it is the first time the possibility occurs
to anybody. An internal decision does not belong on a screen. What the screen
says is what filling the box in buys: *"Shapes what they press on."* Where a
user can read what actually happens to the text is `docs/privacy-policy.md`,
which is what a disclosure is for.

**Measured against the live model, 2026-08-21** — `scripts/audience.py`, 24
composition calls across two archetypes and two conditions:

| | Read the note back | Went to headcount |
| --- | --- | --- |
| Technical Skeptic, no note | 0/6 | 0/6 |
| Technical Skeptic, with note | 0/6 | 1/6 |
| CFO, no note | 0/6 | 0/6 |
| CFO, with note | 0/6 | **2/6** |

Shaped-not-spoken **holds**: nothing was read back in any of the 24 lines. The
steering is real but small — the CFO produced *"how many heads do you need to
reach it?"* and *"how many engineers are doing the migration?"* against an
utterance about a replatform, having asked about neither without the note.

**The scorer undercounts and the numbers are a floor.** `HIRING` contains
`headcount` and not `heads`, so *"how many heads do you need"* was not flagged
by the run that produced it and was counted by hand. Widen the list before
quoting these against anything. And per `scripts/rotation.py`'s own warning, one
run is not evidence — a difference of one is noise.

**The off-domain concern, checked.** The architect asked whether a note about
headcount drags the Technical Skeptic onto the CFO's ground. Once in six, and
the line was *"what happens when those customers demand more engineers to
maintain them without adding headcount"* — a load question wearing a hiring
coat, rather than the Skeptic abandoning its domain. Mild. Worth re-running if
the note ever moves into the system instruction, which would invert the
ordering that currently keeps the persona on top.

## 1a. It must not ask who is in the room

**Corrected 2026-08-21, the same day, by the architect on first sight of a
device.** The field shipped asking *"Who are you presenting to?"* and the
question back was immediate and correct: *"why would a user provide text stating
who they are presenting to — what is the panelist for then?"*

The rail directly below answers that question already, and seating it is the
decision the whole screen exists for. Two questions with one answer reads as a
second picker, and it makes the box look redundant at exactly the moment
somebody decides whether to fill it in.

**What the box is actually for is the thing an archetype structurally cannot
carry.** The eight are shipped constants shared by every user, so "The CFO"
knows to attack cost, margin and runway and *cannot* know that in this company
headcount is the third rail. The panel is the *kind* of person; this is the
*particular* room.

So it asks **"What's this audience like?"** — for a description of character
rather than an identity, which is what keeps it clear of the picker above. (An
earlier line, "What should they know about this room?", carried two pronouns
with no antecedent and could be read as a note about the rehearsal itself; the
architect caught it.) It carries
`Product.md` §3.1's own example verbatim underneath — nobody knows what belongs
in an empty box, and one concrete line does more than a paragraph of
instruction.

The server-side fence label is unchanged. It describes the text to a model that
has no picker to duplicate, it was written to be accurate about the content
rather than about the screen, and changing measured prompt text without a reason
is churn.

## 2. It enters at the composer, and nowhere else

`TurnContext.audience`, beside `pressure`. **Not `Grounding`**, and the
distinction is the feature: `Grounding.claims` render under *"Their material
says:"* and exist to be quoted, because `CLAUDE.md` refuses interrogation logic
that cannot cite its source. This is never citable. Filing it with the claims
would be an invitation for some later caller to render it as one — and a
panelist attributing a text box to a deck is inventing a provenance, which is
exactly the failure #45 measured live.

It sits with `pressure` because that is the other room-constant fact the model
is shown: both are true for every turn of a room, and neither is evidence.

**Selection does not see it.** #43 measured how easily that step is talked into
things — asked to weigh three criteria it gave the CFO seven of eight turns —
and routing by domain already works. Widening the injection surface into the
choice of speaker buys nothing.

## 3. The Auditor never sees it, and admitting it would be harmful

Not merely unnecessary. The Auditor's reference set is *figures*, and every
comparison is ordinary code precisely so arithmetic hallucination is impossible
rather than discouraged. Prose about a colleague is not a claim and cannot be
contradicted.

Worse, if a note carried a number, the user's own note could "disagree" with
their own speech — producing a live false accusation, which
`auditor.TOLERANCE`'s docstring names as the failure to avoid: *"a panel that
pounces on rounding is not intimidating, it is stupid."*

## 4. Per room. Never per account, and never per lineage

The task set the constraint itself: *"a user rehearsing for the same committee
twice should not retype it; a user rehearsing for two different rooms must not
inherit the wrong one."*

- **Per account** is ruled out by the second half. The note is about a specific
  meeting; an account-level default carries the wrong room into every other one.
- **Per lineage** is the interesting near-miss, because `rehearsal_name` works
  exactly that way — the newest name in a group is the group's. But somebody may
  put one argument to their VP on Monday and to the board on Friday. That is one
  rehearsal and two audiences, and lineage resolution would put Monday's note
  silently into Friday's room.
- **Per room** answers both. The retype problem is solved by the path that
  already exists: "Run it again" carries `archetypes`, `material`, `repeats`,
  `name` and `rung` from the Library into the setup screen, and the note joins
  that list. **Inherited where somebody can see it and change it before Start**,
  which is the whole difference between helpful and wrong.

It also puts the text on `sessions`, which is already in
`billing/deletion.PURGED`. A table of its own would be a table somebody forgets
to add there — and #53's description names that failure exactly: nothing
cascades from a *user* by design, so a table left out is personal data retained
forever with nothing raising.

## 5. Fenced, capped at a paragraph, never logged

**Fencing moved to `agents/fencing.py`** when this became the second field a
user's prose reaches a prompt through. The text is byte-identical to what
`authored.py` had, so the custom-archetype room is still the one that was
measured; what changed is that the invariant sentence now exists once. A defence
kept in two copies is one that eventually exists in two versions.

It raises the bar and does not seal the door — `docs/custom-archetypes.md` §2
says so, and #63 is the standing proof that even our own hand-tuned prose can
beat a hard prohibition. What it buys is that the model is told, before it reads
a word, whose words these are and what they are for.

**`AUDIENCE_LIMIT = 400`**, the same as `panels.models.PERSONA_LIMIT` and for
its stated reason: *"a paragraph describes somebody, and a page is room to argue
with the instructions underneath it."* The cap is part of the fencing rather
than a storage concern, which is why the column is `Text` and the limit lives at
the schema, where a 422 can tell the user. Refused rather than truncated, on
`rehearsal_name`'s reasoning — silently storing something other than what was
typed is worse than saying no.

**One field, not two.** §3.1's other example is a *"publicly published fund
thesis"*, which does not fit in a paragraph and should not: a document goes
through ingestion, where it becomes claims the Auditor can actually check. This
box is for the room.

**Never logged, never in `audit_events`.** It is prose about identifiable
colleagues — "my VP", "the CFO who blocked this last time" — which puts it in
the class `CLAUDE.md` forbids logging. Audit rows are append-only besides, so a
name written into one cannot be taken back out. `build_room` logs
`described=bool(audience)`: whether, never what.

## 6. What the coach does not get

The debrief and sparring do **not** receive it, and that is deliberate rather
than an omission. The coach's grounding scope is the transcript, ranked weak
answers, Auditor findings and ingested material. It coaches the *answer*, not
the reason the question was asked — and a coach that knew about the VP would be
one more surface for the note to be read back on, which §1 spent the decision
avoiding.

One line to add later if the debrief turns out to want it. Recorded here so
adding it is a decision rather than a discovery.
