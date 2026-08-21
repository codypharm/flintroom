# Rehearsals — grouping rooms by the argument they are attempts at

**Status: resolved and shipped, 2026-08-21.**

Read before touching `sessions.rehearsal_id`, `sessions.rehearsal_name`,
`app/modules/sessions/rehearsals.py`, the Progress screen, or the Library's
"Run it again".

---

## The question this exists to answer

Progress could answer *"am I getting better"*. It could not answer *"am I
getting better at **this**"*, which is the question a rehearsal product exists
for. The architect put it plainly:

> user needs to know if they are doing well in general and in presenting a
> particular thing

The Library had offered "Run it again" since #84 — the user saying, in as many
words, *this is the same thing again* — and the server was never told. Five
rehearsals of one board readout were five unrelated rooms in a history ordered
only by time.

## What a rehearsal is

A **lineage of rooms**, identified by a group id every room already carries.
There is no `rehearsals` table.

A table was the obvious shape and is refused. It would make `rehearsal_id` a
foreign key, add a row to create on every fresh start, and add something to
clean up on deletion — for a group whose only irreducible property is a name.
`COALESCE(rehearsal_id, id)` is the group, everywhere.

### Decision 1 — the group, never the parent

`repeats` names the room being re-run; the server stores that room's **lineage**
on the new one. A → B → C is one group, not a chain.

A parent pointer would have to be walked to be grouped, and walking it in SQL is
a recursive CTE for something that is one column. Carrying the group makes
grouping a `GROUP BY`.

### Decision 2 — the client says which room, never which group

A group id taken straight from the request would let somebody file a room into
another account's lineage, and Progress would then average two people's
rehearsals together. *"Which room this repeats"* is a claim the server can check
against ownership.

A room the caller does not own answers **404**, not 403: as far as they are
entitled to know, it is not there.

### Decision 3 — nullable, and no backfill

`sessions.rehearsal_id` is nullable because a `NOT NULL` column could not have
landed without breaking inserts from the previously deployed build, which knows
nothing about the field — `CLAUDE.md` requires every migration to stay
compatible with it.

The null stops at the service. `Session.rehearsal` applies the
null-means-itself rule and every read goes through it, so **the wire never
carries a null** and no client holds a branch to express a migration detail.

### Decision 4 — not a foreign key

`rehearsal_id` names a session that may be deleted while its descendants remain.
A cascade would take a whole lineage with it; the later rooms are still rooms,
and still about the same argument.

## What a rehearsal is called

`sessions.rehearsal_name`, `varchar(80)`, nullable, **stored on whichever rooms
were given one**. The newest name in a group is the group's.

### Decision 5 — any room may name the lineage, and the newest wins

The obvious design — only the lineage's root room carries a name — was tried on
paper and rejected. Almost nobody names the first room: they discover on the
third attempt that they are working on a *thing*. A name only the root could
hold would leave that presenter permanently unable to name their rehearsal, and
the screen the name exists for stays headed by a date.

So naming a rehearsal on its fourth attempt names all four, and typing over an
existing name renames it. `rehearsals.py` folds the rows oldest-to-newest into a
dict, which makes "newest wins" a property of the ordering rather than a
comparison written twice.

### Decision 6 — asked once, inherited thereafter

The field sits on the setup screen, above the deck and the panel, because the
name is the room's *subject* and everything below is an answer to it. A re-run
arrives with the name already in the field, carried from the Library — so the
name is typed once per argument rather than once per rehearsal.

The server never requires it on a re-run. Making the client send back a name it
was just given is a round trip that exists only to let a client get it wrong.

### Decision 7 — derived into the field, never into a heading

The first version of this rule was "nothing is derived", and it defeated its own
purpose. Optional fields get skipped, so the common case was a rehearsal headed
by "Started 11 August" — exactly the useless heading the name was built to
replace.

The distinction that matters is not *whether* a name is derived but **where it
appears**. A label applied silently behind somebody's back is one they cannot
correct. A suggestion sitting in the field on the setup screen, before Start, is
one they accept, edit or clear.

So: attaching a deck to a room whose name field is empty fills it with the
deck's filename, tidied (`lib/room/deckName.ts`). Nothing is ever stored that
was not on screen when the room opened, and **nothing is derived at render
time** — an unnamed rehearsal is still headed by when it started, never by the
panel or the deck.

Two properties keep it honest:

- **Only into an empty field.** The setter uses the functional form so it reads
  what is on screen now; a name somebody typed is never overwritten by attaching
  a deck. That is the one route by which this could become silent labelling.
- **Tidied modestly.** The extension goes and separators become spaces. Version
  noise — "v4", "FINAL", "(1)" — is deliberately left: "Q4 final" is a real
  thing to call a rehearsal, and a cleverer rule quietly deletes words somebody
  meant.

`materials.filename` survives the source document, which `docs/ingestion.md`
deletes once extraction succeeds, so this still works on a re-run months later.

### Decision 8 — user text that reaches no model

The name is rendered back to whoever typed it and nowhere else. Nothing in
`agents/` imports the session models, and nothing may start —
`docs/custom-archetypes.md` sets the rule for what user-authored strings may
enter a prompt, and a heading on a history screen has no business in one.

Bounded at 80 characters in three places (the column, `SessionStart`, the input's
`maxLength`) because it is a heading, not a note. Refused at 422 rather than
truncated: silently storing something other than what was typed is worse than
saying no. Whitespace-only is stored as absent — a lineage headed by a blank
line reads as a rendering fault.

## What the screens do with it

**Progress** keeps the whole-history trend at the top — that is "in general" —
and adds one run of attempts per named-or-not lineage below it, drawn with the
same instrument at a narrower scope. A run of one is dropped, and a single
lineage that *is* the whole history is withheld because it is already the trend
above.

**Nothing states a verdict.** Per the architect's constraint on the
room-temperature work — *"we need to be careful to avoid giving user false hope
that they are doing well"* — there is no direction, no delta and no percentage.
The attempts are drawn in order with the rung each was earned at, and what they
add up to is the presenter's to read. Reading a trend out of three points,
against a room whose difficulty moved underneath them, is exactly the false
comfort this screen has refused since it was built.

### Decision 9 — one comparison is allowed, and only one

Refusing *every* comparison was the first version and it overcorrected. The
difficulty argument forbids comparing rooms at **different** rungs; it says
nothing against comparing two rooms at the **same** one, where the confounder is
held constant. Refusing that satisfies the false-hope constraint by abandoning
the question the architect asked twice — *"user needs to know if they are doing
well in general and in presenting a particular thing."*

So `lib/progress/rungs.ts` gathers a rehearsal's attempts by rung and reports
only the rungs it ran at more than once: *"Standard: 4 of 7, then 6 of 7."*

What bounds it:

- **Within one rehearsal only.** Two rooms at Standard about different arguments
  share a number and nothing else. Passing the whole history in would rebuild
  the average across incomparable rooms.
- **Tallies, never a delta.** Nothing subtracts, ranks, arrows or annotates.
  Tests assert the absence of "better", "worse", "improv", arrows and per-cent.
- **Rooms predating the ladder are excluded**, because a null rung is a
  difficulty nobody recorded — folding those together as one shared level is the
  forbidden comparison arriving through the back door.
- **Rooms where nobody was asked anything are excluded.** No proportion, and
  pairing a technical failure with a real attempt reads as somebody collapsing.
- **Silent when there is nothing to say**, which is the common case early on.

**What makes this fire at all** is decision 8 of `docs/difficulty-calibration.md`:
a room that repeats another opens at the rung that rehearsal last ran at. Without
it the rung was read from the account and moved on every debrief — including
debriefs of unrelated arguments — so two adjacent attempts at one pitch could be
pressed differently for reasons nothing to do with that pitch, and this
comparison went silent exactly where it is wanted.

**The Library** leads a row with the name when there is one, demoting the date
to sit beside the panel — what actually distinguishes two rooms is one line of
text. Unnamed rooms are unchanged.

## What is deliberately not built

- **Renaming outside a room.** A rehearsal is renamed by starting another one
  and typing over the name. A rename endpoint is owed if somebody wants to fix a
  typo without spending minutes — reopen it when that is asked for.
- **Merging or splitting lineages.** No signal yet that anybody files an
  argument wrongly and cares.
- **Anything that reads the name to route or judge.** See decision 8.

## The one loose thread

`repeats` survives every edit made on the setup screen after a re-run seeded it.
"The same argument, a harder panel" and "the same argument, a rewritten deck"
are both still that argument, so this is deliberate — but it does mean somebody
who taps "Run it again", then unpicks everything and assembles a genuinely
different room, files it into the old lineage. The recovery is the name field,
which is in front of them and empty of the right words. Revisit if it is ever
reported.
