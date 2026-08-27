"""The Auditor catching a user contradicting themselves.

`docs/auditor-grounding.md` reframes the Auditor as two jobs that had been
collapsed into one word. *Grounding* — a challenge tracing to something specific
— needs only that the user said something, and they are speaking claims
continuously. *Cross-checking* needs a reference, and that is what a deckless
session lacks.

The answer is that **the transcript is the reference**: a running set of figures
the user has stated, checked against each new one. It is also what actually
happens in the format that prompted the question — the sharks have no deck, and
they catch people because the numbers fail against *each other*.

No model here. `docs/auditor-grounding.md` makes the extract/compute split
structural rather than stylistic: the model's only job is pulling figures out of
speech into a typed claim, and every comparison is ordinary code. If the
comparison needed a model to test, the split has leaked.
"""

from __future__ import annotations

import pytest

from app.agents.archetypes import by_name
from app.agents.auditor import Auditor, ClaimReading, SpokenClaim, WrittenClaim
from app.core.errors import ProviderUnavailable
from app.modules.ingestion.schemas import QuantitativeClaim, Unit


def said(
    metric: str,
    value: float,
    *,
    at: int,
    unit: Unit = Unit.PERCENT,
    period: str | None = "Q3 2026",
    quote: str = "spoken",
) -> SpokenClaim:
    return SpokenClaim(
        claim=QuantitativeClaim(
            quote=quote, metric=metric, value=value, unit=unit, period=period
        ),
        at_seconds=at,
    )


def written(
    metric: str,
    value: float,
    *,
    page: int = 5,
    unit: Unit = Unit.PERCENT,
    period: str | None = None,
    quote: str = "on the slide",
) -> WrittenClaim:
    return WrittenClaim(
        claim=QuantitativeClaim(
            quote=quote, metric=metric, value=value, unit=unit, period=period
        ),
        page=page,
    )


def test_a_spoken_figure_is_checked_against_the_deck():
    """The flagship check, wired at last.

    `docs/auditor-grounding.md` names deck-vs-speech as the *exact* check —
    "the slide says 40%, they said 25%" — and the first Play-build room
    (Kettleworks, 2026-08-26) showed it had never been connected: a room
    seeded with planted contradictions produced zero findings, because the
    Auditor's memory started empty and only ever compared speech to speech.
    """
    auditor = Auditor(written=[written("gross margin", 38.0, page=5)])

    caught = auditor.hear(said("gross margin", 60.0, at=125, period=None))

    assert caught is not None
    assert "page 5" in caught.summary
    assert "38" in caught.summary and "60" in caught.summary
    assert "2:05" in caught.summary


def test_a_spoken_figure_agreeing_with_the_deck_is_not_a_catch():
    """Repeating your own slide is the healthiest thing a presenter does."""
    auditor = Auditor(written=[written("gross margin", 38.0)])

    assert auditor.hear(said("gross margin", 38.0, at=90, period=None)) is None
    assert auditor.hear(said("gross margin", 39.0, at=95, period=None)) is None


def test_a_bare_spoken_figure_is_dated_by_the_deck_that_states_a_period():
    """Nobody re-states the slide's period aloud.

    The deck says "gross margin 38% (FY2025)"; the presenter says "margins are
    north of sixty". Refusing to compare because only one side carries a period
    would leave the canonical planted lie uncaught — the same finding `_dated`
    records for speech against speech, applied to the deck.
    """
    auditor = Auditor(written=[written("gross margin", 38.0, period="FY2025")])

    caught = auditor.hear(said("gross margin", 60.0, at=100, period=None))

    assert caught is not None


def test_the_deck_catch_is_owned_by_the_domain_of_its_metric():
    auditor = Auditor(written=[written("gross margin", 38.0)])

    caught = auditor.hear(said("gross margin", 60.0, at=100, period=None))

    assert caught is not None
    assert caught.domain == "margin"


def test_the_reader_is_told_the_decks_metrics_too():
    """Name reuse is what makes `_same_metric` work at all.

    The reader invents metric names from the sentence it reads. Handed the
    deck's names up front, it reuses them — and a spoken claim extracted under
    a different spelling of the same metric is a catch that never fires.
    """
    auditor = Auditor(written=[written("gross margin", 38.0)])

    assert "gross margin" in auditor.metrics()


def test_a_figure_that_moved_is_caught_with_both_numbers_and_both_moments():
    """The tracer bullet, and the bar the doc sets for interrupting a live room.

    *"A contradiction the Auditor can state precisely: both figures, both
    moments."* Anything vaguer is a panel asserting that something is wrong
    without being able to say what, which is worse than saying nothing — it
    hands the user a reason to dismiss everything else in the session.

    Both moments matter as much as both figures. "You said sixty-one and then
    seventy" is an accusation; "at two minutes you said sixty-one, at nine you
    said seventy" is evidence, and the difference is whether the user can check
    it.
    """
    auditor = Auditor()

    assert auditor.hear(said("gross margin", 61, at=120)) is None
    caught = auditor.hear(said("gross margin", 70, at=540))

    assert caught is not None
    assert "61" in caught.summary and "70" in caught.summary
    assert "2:00" in caught.summary and "9:00" in caught.summary


def test_a_person_rounding_their_own_number_is_not_contradicting_themselves():
    """*"A false accusation is worse than a missed catch."*

    The doc's own example: *"About forty then thirty-eight is not a
    contradiction, it is a person talking."* Nobody speaks to two decimal
    places, and a panel that pounces on rounding is not intimidating — it is
    stupid, and it hands the user a reason to dismiss everything else it says.

    This is the test that matters more than the true positive above. A missed
    catch costs one challenge; a false one costs the room its credibility, and
    credibility is the entire product.
    """
    auditor = Auditor()

    auditor.hear(said("gross margin", 40, at=60))

    assert auditor.hear(said("gross margin", 38, at=300)) is None


def test_the_same_disagreement_is_judged_the_same_whichever_way_it_ran():
    """A figure revised down must be treated exactly as one revised up.

    The gap between 92 and 100 is one disagreement, and which number was said
    first is a fact about the conversation rather than about the arithmetic.
    Measured against the earlier figure it is 8% going down and 8.7% going up,
    so a threshold between them catches a user who revises downward and forgives
    the identical revision upward — a room that is harsher on people admitting a
    number was worse than they said, which is precisely backwards.

    Written after the mutation survived. The reasoning was in the docstring and
    nothing held it there.
    """
    falling, rising = Auditor(), Auditor()

    falling.hear(said("headcount", 100, at=60, unit=Unit.COUNT))
    rising.hear(said("headcount", 92, at=60, unit=Unit.COUNT))

    fell = falling.hear(said("headcount", 92, at=300, unit=Unit.COUNT))
    rose = rising.hear(said("headcount", 100, at=300, unit=Unit.COUNT))

    assert (fell is None) == (rose is None)


def test_two_figures_about_different_periods_never_disagree():
    """*"Last quarter's revenue against last year's is not a contradiction."*

    The doc names comparability as the source of most false positives, and this
    is the sharpest case: the two numbers *should* differ, and a room that
    challenges somebody for growing is a room that has not understood the
    sentence.

    `QuantitativeClaim.comparable_to` already enforces it, and this asserts it
    from the Auditor's side anyway. The guard lives in a type this module does
    not own, and a well-meant relaxation of it there would silently turn every
    growing metric in every session into an accusation — with nothing in
    ingestion's own tests to object, because ingestion never compares two
    spoken figures.
    """
    auditor = Auditor()

    auditor.hear(said("revenue", 400_000, at=60, unit=Unit.USD, period="Q1 2026"))
    later = auditor.hear(
        said("revenue", 900_000, at=300, unit=Unit.USD, period="Q3 2026")
    )

    assert later is None


def test_a_figure_restated_unchanged_is_somebody_being_consistent():
    """The commonest thing in a rehearsal, and it must be silent.

    People repeat their headline number — it is the one they have practised.
    Every repetition is a chance for the Auditor to fire, so a room that treats
    restatement as contradiction gets louder the more consistent the user is,
    which inverts the entire signal.
    """
    auditor = Auditor()

    auditor.hear(said("ARR", 1_200_000, at=45, unit=Unit.USD))

    assert auditor.hear(said("ARR", 1_200_000, at=400, unit=Unit.USD)) is None


# --- Reading figures out of speech -----------------------------------------
#
# The model's entire job, and the boundary `mocking.md` allows a fake at. What
# stays real is everything we decide: when a claim is stamped, what happens to
# the room when the model fails, and what a reading costs.


class ScriptedReader:
    """A claim reader that answers with whatever the test handed it."""

    def __init__(self, *readings: ClaimReading) -> None:
        self._readings = list(readings)
        self.heard: list[str] = []
        self.known: list[tuple[str, ...]] = []

    async def read(self, *, said: str, known_metrics: tuple[str, ...] = ()) -> ClaimReading:
        self.heard.append(said)
        self.known.append(known_metrics)
        return self._readings.pop(0) if self._readings else ClaimReading()


def figure(metric: str, value: float, *, unit: Unit = Unit.PERCENT,
           period: str | None = "Q3 2026") -> QuantitativeClaim:
    return QuantitativeClaim(
        quote="spoken", metric=metric, value=value, unit=unit, period=period
    )


async def test_a_figure_spoken_now_is_checked_against_one_spoken_earlier():
    """The tracer bullet for the live path: speech in, a grounded catch out.

    The Auditor's comparison is pure and needs no model; this is the edge where
    a model turns an utterance into something comparable. Two responsibilities
    meet here and only one of them is the model's — it reads figures out of
    speech, and the room decides what they mean.

    The moment is stamped here rather than by the model, deliberately. A model
    asked what time it is will answer, plausibly and wrongly, and the timestamp
    is half the evidence a panelist puts to the user.
    """
    reader = ScriptedReader(
        ClaimReading(claims=(figure("gross margin", 61),)),
        ClaimReading(claims=(figure("gross margin", 70),)),
    )
    auditor = Auditor(reader=reader)

    assert await auditor.listen("Our gross margin is sixty-one.", at_seconds=120) is None
    caught = await auditor.listen("Margin is seventy percent.", at_seconds=540)

    assert caught is not None
    assert "61" in caught.summary and "70" in caught.summary
    # The moments come from the caller's clock, which is the point of stamping
    # them here. A reading that lost them would still name both figures and
    # would be an accusation the user cannot check.
    assert "2:00" in caught.summary and "9:00" in caught.summary
    assert reader.heard == ["Our gross margin is sixty-one.", "Margin is seventy percent."]


async def test_a_reader_that_fails_costs_a_catch_and_never_the_room():
    """A live metered interrogation must not end because a side-channel broke.

    The Auditor is a background improvement to a room that already works: the
    panel challenges what the user said whether or not anything was extracted.
    Letting a reader failure propagate would take down a session — settling it,
    refunding it, and losing the user the room they came for — over the loss of
    one *additional* kind of question.

    The same trade `select_speaker` makes for routing, and for the same reason:
    in a live room a pause with nobody in it is the failure a user notices
    first.
    """

    class Broken:
        async def read(self, *, said: str, known_metrics=()) -> ClaimReading:
            raise ProviderUnavailable(reason="claim_reader_error")

    auditor = Auditor(reader=Broken())

    assert await auditor.listen("Our margin is seventy.", at_seconds=60) is None


async def test_a_deployment_with_no_reader_still_runs_rooms():
    """One unconfigured model must not take the interrogation with it.

    Same shape as `build_speaker` and `build_panel_model`: the process boots,
    says so once, and the feature is absent rather than fatal. A room without a
    claim reader still transcribes, routes, composes, speaks and captions — it
    simply never catches a figure moving.
    """
    auditor = Auditor()

    assert await auditor.listen("Our margin is seventy.", at_seconds=60) is None


def test_a_metric_the_model_capitalised_differently_is_the_same_metric():
    """Measured against live Gemini, and it does this constantly.

    Eight utterances produced `gross margin`, `Revenue`, `Churn`, `engineers`
    and `pre-money valuation` — the model matches the shape of the sentence it
    read, so the same figure arrives capitalised one way at minute two and
    another at minute nine. Under exact string equality those are two different
    metrics and the contradiction is never checked.

    It fails silently and in the safe direction, which is what makes it worth a
    test: nothing errors, no false accusation is made, the room simply stops
    catching things and looks exactly like a room where the user was
    consistent.
    """
    auditor = Auditor()

    auditor.hear(said("Revenue", 400_000, at=60, unit=Unit.USD))

    assert auditor.hear(said("revenue", 900_000, at=300, unit=Unit.USD)) is not None


def test_a_catch_is_labelled_with_the_domain_that_owns_it():
    """Without this, targeted interruption routes to nobody.

    §3.3 assigns the interrupter by domain — the CFO catches the margin
    contradiction, not the Technical Skeptic — and `panel._owner` matches
    `Finding.domain` against the canonical domains an archetype declares:
    `margin`, `headcount`, `compliance`. A model reads a metric out of speech in
    the speaker's own words, which is *"gross margin"*, and that matches nothing.

    The failure is silent and looks like success. `_owner` returns `None`, the
    turn falls through to ordinary routing, somebody speaks, the transcript
    reads fine — and the single most differentiated behaviour in the product is
    off, with `chosen_by=model` in the logs to say everything is well.

    `vocabulary.py` predicted this in its own docstring: *"the real fix is
    routing on the claims the Auditor already extracts from live speech — those
    carry the metric explicitly, so a figure about acquisition cost arrives
    labelled rather than guessed at."* This is that fix, using the same table.
    """
    auditor = Auditor()

    auditor.hear(said("gross margin", 61, at=120))
    caught = auditor.hear(said("gross margin", 70, at=540))

    assert caught is not None
    assert caught.domain == "margin"
    assert "margin" in by_name("cfo").domains


def test_a_metric_no_archetype_owns_still_produces_a_catch():
    """An unowned domain is a real contradiction with nobody obvious to raise it.

    `_owner` already answers `None` rather than forcing it on somebody, and
    lets ordinary selection run — the alternative produces the *"engineer
    challenges the margin"* failure §3.3 exists to prevent. So the finding must
    still exist and still be stateable; only its routing is undecided.

    Dropping it instead would mean the Auditor silently ignores every figure
    outside the eight archetypes' vocabulary, which is most figures in most
    industries.

    The example used to be *"widget throughput"*, and it stopped being unowned
    when the Technical Skeptic was generalised off software (#81): `throughput`
    is now one of `capacity`'s words, and she is exactly the right person to ask
    why it more than doubled. That is the table working, not this test breaking
    — so the example moved to a figure the vocabulary genuinely has no word for,
    which is the case this is about.
    """
    auditor = Auditor()

    auditor.hear(said("pallets shipped", 400, at=60, unit=Unit.COUNT))
    caught = auditor.hear(said("pallets shipped", 900, at=300, unit=Unit.COUNT))

    assert caught is not None
    assert "400" in caught.summary and "900" in caught.summary
    # Labelled with what was actually said, rather than blanked. No archetype
    # will match it and none should — but a finding nobody owns still appears in
    # logs and in the debrief, and "pallets shipped" says which figure moved
    # where an empty domain says nothing at all.
    assert caught.domain == "pallets shipped"


async def test_the_reader_is_told_which_metrics_are_already_in_play():
    """The scalable answer to "margin" meaning "gross margin".

    Measured against live Gemini on real sentences: *"our gross margin held at
    sixty-one percent"* then *"the margin is closer to seventy percent"*
    produced `gross margin` and `margin`. Two metrics, no contradiction, and the
    single case the whole feature exists to catch went unremarked.

    Lowercasing does not reach it. Neither does stripping qualifiers, which is
    the obvious fix and a trap: **gross margin and net margin are different
    numbers**, and merging them manufactures a contradiction out of two true
    statements — the expensive direction. A synonym table cannot reach it either.
    Every industry names its own metrics, and the failure mode of a table that
    over-matches is a false accusation rather than a missed catch.

    So the reader is shown what has already been named and asked to reuse a name
    when the speaker is plainly referring to it. That stays on the right side of
    the extract/compute split: resolving *"the margin"* to the metric under
    discussion is reading language, which is the model's job. Deciding that two
    numbers disagree remains ordinary code.
    """
    reader = ScriptedReader(
        ClaimReading(claims=(figure("gross margin", 61),)),
        ClaimReading(claims=(figure("gross margin", 70),)),
    )
    auditor = Auditor(reader=reader)

    await auditor.listen("Our gross margin held at sixty-one.", at_seconds=8)
    await auditor.listen("The margin is closer to seventy.", at_seconds=24)

    assert reader.known == [(), ("gross margin",)]


def test_a_figure_restated_without_a_period_is_about_the_same_period():
    """How people actually talk, and what the live run proved we were missing.

    Measured against real sentences: *"our gross margin held at sixty-one
    percent last quarter"* then *"the margin is closer to seventy percent"*.
    The second names no period, because nobody repeats one — they said it once
    and the conversation is still about it. Requiring both to state a period
    left the canonical contradiction, the one this whole feature exists for,
    silently uncaught even after the metric names were resolved.

    So a figure with no period stated inherits the last period stated for that
    metric, which is what a person in the room does. Per metric, never across
    one: revenue's quarter says nothing about what margin refers to.

    This is inference, and it is the aggressive option of the three considered.
    The failure it risks is real — somebody who says "revenue was 400k in Q1"
    and later "revenue is 900k" meaning today would be challenged for growing —
    which is why the assumption is stated in the finding rather than hidden, so
    the challenge can be checked and refused by the user rather than only
    endured.
    """
    auditor = Auditor()

    auditor.hear(said("gross margin", 61, at=8, period="last quarter"))
    caught = auditor.hear(said("gross margin", 70, at=24, period=None))

    assert caught is not None
    assert "61" in caught.summary and "70" in caught.summary
    # The inferred period is on the record. A user challenged on an assumption
    # they can see is a user who can correct it; one challenged on a hidden
    # assumption can only conclude the room is wrong about something.
    assert "last quarter" in caught.summary


def test_one_metrics_period_never_becomes_another_metrics_period():
    """Inheritance is per metric, or it invents comparisons out of nothing.

    A session states a quarter once, while discussing revenue, and then talks
    about six other figures without repeating it. If any bare period could pick
    up any earlier one, every metric in the room would silently be dated from a
    single sentence — turning a guard that exists to reduce false positives into
    the largest source of them.

    The ordering here is the whole test, and the first version of it was
    vacuous: revenue's quarter has to be the *most recent* stated period, so a
    lookup that ignored the metric would reach it before the margin's own. With
    revenue merely earlier, both the correct code and the broken code agreed,
    and the mutation survived.
    """
    auditor = Auditor()

    auditor.hear(said("gross margin", 61, at=10, period="Q3 2026"))
    auditor.hear(said("revenue", 400_000, at=20, unit=Unit.USD, period="Q1 2026"))
    caught = auditor.hear(said("gross margin", 70, at=40, period=None))

    assert caught is not None, "the margin borrowed revenue's quarter and stopped matching"
    assert "Q3 2026" in caught.summary


def test_a_bare_figure_takes_the_period_most_recently_stated_for_it():
    """The context you are in is the last one named, not the first.

    A speaker who talks about Q1, then moves to Q3, and then says a bare number
    means Q3 — they have moved the conversation on. Reaching for the earliest
    period instead would date every later figure from the opening sentence of
    the session, and would then compare it against a quarter nobody has
    mentioned for ten minutes.

    Both orderings produce *a* catch here, which is why the assertion is on
    which one: the summary has to name the figure actually being contradicted,
    or the panelist quotes a number the user has already superseded.
    """
    auditor = Auditor()

    auditor.hear(said("gross margin", 61, at=10, period="Q1 2026"))
    auditor.hear(said("gross margin", 90, at=20, period="Q3 2026"))
    caught = auditor.hear(said("gross margin", 70, at=40, period=None))

    assert caught is not None
    assert "Q3 2026" in caught.summary and "90" in caught.summary
