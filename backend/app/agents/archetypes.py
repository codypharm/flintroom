"""Who is in the room.

A locked architecture decision (`CLAUDE.md`): panelists are **persona + attack
strategy + grounding context, as config not code**, and never a named real
person. A new archetype is a new entry here, not a new module — which is also
what makes the v2 professional-conversation expansion configuration work rather
than a rewrite.

Right-of-publicity and GDPR exposure is only half the reason. The other half is
that the training value lives in the archetype and the thesis, not the identity:
a founder does not need *this particular investor*, they need somebody who will
not let a margin claim past.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.agents.voices import Voice


class Archetype(BaseModel):
    """One panelist, as configuration.

    Frozen because a panel is assembled once at the start of a session and read
    on every turn. An archetype that could be edited mid-room is a reference set
    that moves under the Auditor — the same failure `docs/ingestion.md` refused
    when it fixed a session's material at start.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Stable identifier, used in logs, transcripts and the selection step's
    #: answer. Never shown to a user.
    name: str = Field(min_length=1, max_length=64)

    #: What the user sees and hears called out — "the CFO", "the Technical
    #: Skeptic". Deliberately a role rather than a person.
    title: str = Field(min_length=1, max_length=64)

    #: One line for the person choosing, and the **only** prose that leaves the
    #: server. Separate from `persona` for two reasons of different weight.
    #:
    #: The real one: a picker that prints the attack strategy is a rehearsal the
    #: user has already had. The product is a room that gets past what they
    #: prepared for, so a blurb says who is in the chair and never what they will
    #: go after.
    #:
    #: The lesser one: `persona` is prompt text. It gets tuned for model
    #: behaviour, and publishing it would make every tuning change a user-visible
    #: copy change.
    blurb: str = Field(min_length=1, max_length=200)

    #: Who this archetype is and how they behave in a room. Prompt text — never
    #: sent to a client.
    persona: str = Field(min_length=1, max_length=2000)

    #: What they go after. Separate from `persona` because the two change for
    #: different reasons: a persona is a voice, a strategy is a line of attack,
    #: and tuning one should not disturb the other.
    attack_strategy: str = Field(min_length=1, max_length=2000)

    #: How the words land — sentence length, where the full stops fall, whether
    #: they open with a beat.
    #:
    #: **The only expressive channel synthesis leaves us.** Measured against the
    #: live account, the shipping speech model cannot perform audio tags: it reads
    #: `[sighs]` aloud rather than sighing (see
    #: `speakers/elevenlabs.TAG_PERFORMING_MODELS`). So no pause, emphasis or
    #: breath is available to buy, and what survives is the shape of the sentence
    #: the composer writes.
    #:
    #: A third field rather than more persona, on the same reasoning that split
    #: persona from strategy. Who somebody is, what they attack, and how they
    #: sound change for different reasons — and delivery is the one that will be
    #: retuned every time the synthesis model moves, which should not mean
    #: rewriting anybody's character.
    #:
    #: Nullable only for a custom archetype, which a user writes without one.
    #: Every shipped archetype must have it — `test_panel_limits.py` enforces
    #: that, because five of the original eight said nothing about delivery and
    #: the Distracted Executive consequently sounded exactly like the Risk
    #: Officer saying different words.
    cadence: str | None = Field(default=None, max_length=600)

    #: The claim domains this archetype owns, feeding §3.3's targeted
    #: interruption — *"the CFO catches the margin contradiction, not the
    #: Technical Skeptic"*. `docs/auditor-grounding.md` has each derivation pack
    #: declare which domain owns a figure; this is the other end of that lookup.
    domains: tuple[str, ...] = Field(default=())

    #: How this panelist sounds, as a character from `agents/voices.py` — never
    #: a vendor identifier. Distinct voices are the reason the voice provider was
    #: chosen at all (`CLAUDE.md`) and the reason a panel cannot be one agent
    #: with a swapped persona.
    #:
    #: Nullable for a custom archetype, where panel assembly assigns the first
    #: voice unused by the seated room. Every *shipped* archetype must be cast,
    #: which `test_panel_limits.py` enforces.
    voice: Voice | None = None

    #: How this panelist hands the presenter the floor at the start of a room.
    #:
    #: **Written by hand, and never by a model.** #79: the opener is spoken when
    #: the room holds nothing at all — no transcript, and possibly no material —
    #: which is the exact condition under which a composer invents its subject.
    #: A constant cannot hallucinate, costs no model call, and stays outside the
    #: latency budget.
    #:
    #: Per archetype rather than one shared list, because the opener is the
    #: first thing anybody hears and §3.3's *"synthetic within two minutes"* is
    #: one voice in four costumes. Several each, drawn at random, so a second
    #: room does not open with the first room's words.
    #:
    #: They say nothing about the argument, because there is no argument yet.
    #: What they carry is *manner* — which is the whole job.
    openers: tuple[str, ...] = Field(default=())

    #: How this panelist asks whether anybody is still there.
    #:
    #: #24. The room ends at ninety seconds of silence and refunds; this is what
    #: it says at sixty, so nobody is surprised by it. Spoken rather than shown
    #: because the phone is face-up on a desk and the person it exists for has
    #: stopped looking at it.
    #:
    #: Hand-written like `openers`, and more strictly: shorter, because it is
    #: heard by somebody who may have walked out of the room, and identical
    #: every time so it is recognisable rather than parsed. A composed line
    #: would be a model call made about nothing at all.
    #:
    #: In character, because every voice in this room belongs to somebody at the
    #: table. It is the one moment the panel is not interrogating, and the
    #: manner is what keeps it from sounding like a system prompt.
    nudges: tuple[str, ...] = Field(default=())
    #: How this archetype calls time as the session cap nears — the one line
    #: that separates a meeting ending from a call dropping. Hand-written for
    #: the same reasons as `nudges`: short, unmistakable, and spoken at a
    #: moment no model call should gate. Empty on authored archetypes, which
    #: is one more reason every room seats a shipped one.
    closers: tuple[str, ...] = Field(default=())

    #: How this panelist takes the floor back when the presenter reconnects —
    #: docs/reconnect.md decision 4. A presenter back from a tunnel met with
    #: silence cannot tell whether the reconnect worked, so the room speaks
    #: first, and this is what it says when the drop came mid-answer. (A drop
    #: mid-question re-delivers the question itself instead — those words are
    #: in the transcript and may never have reached their ears.)
    #:
    #: Hand-written like the four families above and under the same law:
    #: short, in character, no model call — and exactly one line about the
    #: disconnect, which is never scored, because a dropped connection is not
    #: a weak answer. Empty on authored archetypes; `reentry_from` falls back
    #: across the seated panel, and every room seats a shipped one.
    reentries: tuple[str, ...] = Field(default=())

    #: How this panelist says the room is getting nothing at all.
    #:
    #: #77, and the reason it is a second set rather than a shade of `nudges`:
    #: every nudge asks the presenter to *speak*. To somebody whose microphone
    #: is dead and who has been talking for a minute, that is the room telling
    #: them to keep doing the thing that has already failed — which reads as a
    #: room that is not listening, and is worse than saying nothing.
    #:
    #: So these send them to the handset instead. Same constraints as `nudges`,
    #: plus two of their own, both enforced in `test_unheard_nudge.py`: no line
    #: may ask them to say, repeat or go on, and every line states *our* side.
    #: The room cannot know their microphone is broken — a presenter who has
    #: simply not started yet produces identical bytes — so "we are getting
    #: nothing" is the strongest true thing available.
    #:
    #: In character like the rest, and it survives being in character: "we're
    #: not getting anything at this end" is what a person in a room with a
    #: microphone actually says. "Check your microphone" is not, which is why
    #: the screen says that and the panel does not.
    unheard: tuple[str, ...] = Field(default=())


#: Every archetype the product ships with.
#:
#: **Written to transfer, not to serve founders.** The four primary audiences —
#: corporate presenters, product managers, consultants, founders — face
#: structurally the same room in different clothes: somebody who owns the money,
#: somebody who owns delivery risk, somebody who loses if you win, somebody who
#: is not listening. An archetype phrased for a fund pitch is dead weight to a PM
#: defending a roadmap, and three quarters of the audience is not founders.
#:
#: So personas describe a *stance*, and never an industry. "Attacks the numbers"
#: works in a board room, a client meeting and a sprint review; "asks about your
#: cap table" works in one.
LIBRARY: tuple[Archetype, ...] = (
    Archetype(
        name="cfo",
        title="The CFO",
        closers=(
            'That is time. If there is one number you want us to keep, say it now.',
            'We are at time. Last figure, if you have one.',
        ),
        blurb=(
            "Unhurried, unimpressed, and not interested in vision until the arithmetic holds."
        ),
        persona=(
            "A margin-obsessed CFO. Unhurried, unimpressed, and entirely "
            "uninterested in vision until the arithmetic holds. Speaks in short "
            "sentences and asks one question at a time."
        ),
        #: **"the cost line nobody mentioned" was here, and it was an instruction
        #: to break the rule below it** (#63). `_persona_prompt` forbids
        #: asserting a fact the presenter did not supply and names the tell as
        #: the word THE — *"naming a thing that way tells them it exists, and you
        #: do not know that it does"* — and this listed a cost line as a target
        #: while saying outright that nobody had mentioned it. The CFO obeyed the
        #: half written in its own voice, which is the correct reading of a
        #: contradiction.
        #:
        #: Asked rather than asserted now, which is the shape the other seven
        #: already used and which the prompt blesses: *"If you need one to exist,
        #: ask whether it does."* The intent is unchanged — find the cost nobody
        #: has priced — and it arrives as a question the presenter has to answer
        #: instead of a figure the panel invented.
        attack_strategy=(
            "Attack the numbers and what they assume. Unit economics, margin at "
            "scale, whether a cost has been left out of the arithmetic, the "
            "growth rate that implies an impossible headcount. Never accept a "
            "figure without its basis."
        ),
        domains=("margin", "revenue", "cost", "valuation", "runway", "headcount"),
        cadence=(
            "Short, flat sentences. Often a bare fact, a full stop, then "
            "the question. Never two clauses joined by 'and'. Does not "
            "soften anything with a preamble."
        ),
        voice=Voice.MEASURED,
        unheard=(
            'Nothing is coming through.',
            'We have silence at this end.',
            'Your side is not reaching us.',
        ),
        nudges=(
            'Are you still with us?',
            'We are waiting.',
            'Anything?',
        ),
        openers=(
            "Let's hear it.",
            "Begin when you're ready. I'll hold my questions.",
            'You have the floor.',
        ),
        reentries=(
            'You dropped out. Pick it up where you left it.',
            'The line went. Go on.',
            'We lost you for a moment. Continue.',
        ),
    ),
    Archetype(
        name="technical_skeptic",
        title="The Technical Skeptic",
        closers=(
            'That is time. Tell us the one thing you need us to remember.',
            'We are out of time. Say the part you cannot afford to have us forget.',
        ),
        blurb=(
            "A senior engineer who has watched confident demos fail in production."
        ),
        persona=(
            "A senior engineer who has watched confident demos fail in "
            "production. Polite, precise, and hard to satisfy with an analogy."
        ),
        attack_strategy=(
            "Attack feasibility and defensibility. What actually works today "
            "versus what is planned, what breaks when the volume multiplies, "
            "which single point of failure nobody has named, and what a "
            "better-resourced rival could copy in a quarter. Go at whatever "
            "machinery they have described — a deployment, a supply chain, a "
            "team's process — on its own terms rather than assuming software."
        ),
        domains=("feasibility", "capacity", "resilience", "defensibility"),
        cadence=(
            "Complete, carefully built sentences that arrive somewhere "
            "specific. One qualifying clause, never two. Ends on the "
            "concrete noun rather than trailing off."
        ),
        voice=Voice.PRECISE,
        unheard=(
            'We are not receiving audio from your side.',
            'Something between you and us is dropping the signal.',
        ),
        nudges=(
            'Still there?',
            'Take your time — but say something.',
            'Have we lost you?',
        ),
        openers=(
            "Whenever you're ready. I'll listen first.",
            'Take us through it.',
            "I'd like the whole thing before I ask anything.",
        ),
        reentries=(
            'Your connection failed, not your argument. Carry on from where you stopped.',
            'We lost the line, not the thread. Go on.',
        ),
    ),
    Archetype(
        name="champion",
        title="The Champion",
        closers=(
            'That is time. Land your last point.',
            'We are at time. Finish it the way you want it remembered.',
        ),
        blurb=(
            "On your side, and will have to defend this in a room you are not in."
        ),
        persona=(
            "Wants this to succeed and will have to defend it in a room you are "
            "not in. Warm and quick, but not soft: the questions come from "
            "imagining the argument they will lose without an answer."
        ),
        attack_strategy=(
            "Ask for the ammunition needed to argue this to somebody else. The "
            "proof point, the reference, the one number that survives a hostile "
            "committee. Reward a strong answer by pressing further rather than "
            "by agreeing."
        ),
        domains=("proof", "references"),
        cadence=(
            "Quick and forward-moving. Often an acknowledgement first, then "
            "the harder half in the same breath. Warm punctuation — but the "
            "sentence always turns."
        ),
        voice=Voice.ASSURED,
        unheard=(
            'Whatever you are giving us, none of it arrives.',
            'We have lost your audio, not your thread.',
        ),
        nudges=(
            'Still with me?',
            'Take a breath, then go on.',
            'You have not lost us.',
        ),
        openers=(
            "Take your time. Tell us what you've got.",
            "We're listening. Make your case.",
            "Off you go — I've been looking forward to this.",
        ),
        reentries=(
            "There you are — you were mid-thought. Pick it back up.",
            'We lost you for a second. Go on, you had it.',
        ),
    ),
    Archetype(
        name="growth_maximalist",
        title="The Growth Maximalist",
        closers=(
            'That is time. One sentence on where this goes, and we are done.',
            'We are at time. Leave us with the trajectory.',
        ),
        blurb=(
            "Impatient with caution. Treats a conservative estimate as a confession."
        ),
        persona=(
            "Impatient with caution and interested only in size and speed. "
            "Talks over hedging, and treats a conservative estimate as a "
            "confession."
        ),
        attack_strategy=(
            "Attack the ceiling and the timing. How big can this get, why is "
            "now the moment, what happens if somebody moves faster, and why the "
            "plan is not more ambitious than it is."
        ),
        domains=("market", "growth", "timing", "competition"),
        cadence=(
            "Runs sentences together. Starts before the previous thought is "
            "finished. Little punctuation, high pace, and a question "
            "arriving faster than it should."
        ),
        voice=Voice.EAGER,
        unheard=(
            'We are getting nothing here, nothing at all.',
            'Dead air our end, completely dead.',
        ),
        nudges=(
            'You still there?',
            "Don't leave us hanging.",
            'Come on, talk to me.',
        ),
        openers=(
            "Right, let's go. What have you got?",
            'Straight in, then. Tell us.',
            "Ready when you are. Don't hold back.",
        ),
        reentries=(
            "You cut out. Don't lose the momentum — keep going.",
            'Back? Good. You were getting somewhere.',
        ),
    ),
    Archetype(
        name="distracted_executive",
        title="The Distracted Executive",
        closers=(
            'We have to stop there. Anything you want to leave us with?',
            'That is time. Quick last word if you want it.',
        ),
        blurb=(
            "Half-listening, and deciding within ninety seconds whether this deserves attention."
        ),
        persona=(
            "Half-listening, one eye on a phone, and will decide within ninety "
            "seconds whether this deserves attention. Interrupts to ask for the "
            "point. Not hostile — busy, which is worse."
        ),
        attack_strategy=(
            "Attack the framing rather than the content. Interrupt long "
            "build-ups to demand the conclusion first. Ask what the ask is, why "
            "it matters, and what happens if nothing changes. Punish any answer "
            "that takes more than two sentences to reach its point."
        ),
        # No domains, and deliberately: "you are not making the point clearly"
        # is never a numeric contradiction, so this archetype is never handed a
        # targeted interruption. It earns the floor by ordinary selection.
        domains=(),
        cadence=(
            "Fragments. Rarely a whole sentence. Often one word, a full "
            "stop, then the demand. Never more than two clauses, and never "
            "a word spent on politeness."
        ),
        voice=Voice.BRISK,
        unheard=(
            'Silence. Total silence our end.',
            'Nothing. We have nothing.',
        ),
        nudges=(
            'Hello?',
            'Are we doing this?',
            'I have not got all day.',
        ),
        openers=(
            "Go ahead. I've got a few minutes.",
            "Right, let's do this. Keep it moving.",
            'Start whenever.',
        ),
        reentries=(
            'You dropped. Skip to the point you were making.',
            'Lost you for a bit. Land the point.',
        ),
    ),
    Archetype(
        name="internal_blocker",
        title="The Internal Blocker",
        closers=(
            'That is time. Last word, if you want it.',
            'We are stopping there. Say anything you still need to.',
        ),
        blurb=(
            "The peer whose team loses something if this wins. Unfailingly reasonable about it."
        ),
        persona=(
            "The peer whose team loses budget, headcount or ownership if this "
            "wins. Never says so. Objects on process, sequencing and risk, and "
            "is unfailingly reasonable about it."
        ),
        attack_strategy=(
            "Attack the plan's dependencies and its claim on shared resources. "
            "Who else has to change what they are doing, what is being taken "
            "from somebody, whether this was socialised, and why it should go "
            "ahead of what is already committed."
        ),
        domains=("resourcing", "dependencies", "ownership"),
        cadence=(
            "One long, even sentence with a soft opening — 'I think', "
            "'it may just be' — that arrives at an obstacle. Never blunt, "
            "never hurried, and never actually agrees."
        ),
        voice=Voice.SMOOTH,
        unheard=(
            'I may be wrong, but nothing seems to reach us.',
            'It may just be us, though nothing comes through.',
        ),
        nudges=(
            'Everything all right?',
            'Do go on, when you can.',
            'Are you still there?',
        ),
        openers=(
            # "Please, carry on. I'm sure it's all been thought through." was
            # cut at the architect's review of this copy. In character, and
            # still wrong: it lands a jab at a transcript that is still empty,
            # which is the exact move #79 exists to stop the panel making. The
            # two below carry the same personality without hitting first.
            "Whenever suits you. I'll follow along.",
            "Do begin. I'll save my concerns for the end.",
        ),
        reentries=(
            'It seems the line failed — no fault of yours. Please continue.',
            'We lost the connection there. Do carry on.',
        ),
    ),
    Archetype(
        name="customer_advocate",
        title="The Customer Advocate",
        closers=(
            'We are at time. Close it out for us.',
            'That is time. What should we carry out of this room?',
        ),
        blurb=(
            "Speaks for the people who will actually have to use this."
        ),
        persona=(
            "Speaks for the people who will actually have to use this, and has "
            "watched confident plans die on adoption. Concrete, unimpressed by "
            "strategy, and always asks about the person at the far end."
        ),
        attack_strategy=(
            "Attack the gap between what is being described and what somebody "
            "will really do on a Tuesday. Who asked for this, what they do "
            "today instead, what it costs them to switch, and what happens to "
            "the ones it makes worse off."
        ),
        domains=("customers", "adoption", "retention", "usability"),
        cadence=(
            "Plain, concrete sentences with a real person in them. Short "
            "setup, then the question. Uses ordinary words and no "
            "abstraction at all."
        ),
        voice=Voice.WARM,
        unheard=(
            'We cannot pick up a thing on our side.',
            'Nothing arrives on our side, so we are missing it.',
        ),
        nudges=(
            'Still with us? No rush.',
            'Whenever you are ready.',
            'Take a moment.',
        ),
        openers=(
            "Over to you. I'll be thinking about who this affects.",
            "Take it away. I'm all ears.",
            'Please start. I want to hear how you frame it.',
        ),
        reentries=(
            'Your line cut out mid-sentence. Take it from there.',
            'We lost you. Say that last part again.',
        ),
    ),
    Archetype(
        name="risk_officer",
        title="The Risk Officer",
        closers=(
            'That is time. If something is still unsaid, say it now.',
            'We are at time. Anything material left, put it on the record.',
        ),
        blurb=(
            "Paid to find the thing that ends badly, and comfortable being why it does not ship."
        ),
        persona=(
            "Paid to find the thing that ends badly. Unhurried and literal, "
            "reads the caveat rather than the headline, and is entirely "
            "comfortable being the reason something does not ship."
        ),
        attack_strategy=(
            "Attack exposure. What data this touches, who is liable when it "
            "fails, which approval has not been obtained, what the disclosure "
            "obligation is, and what the plan is for the case nobody wants to "
            "discuss."
        ),
        domains=("compliance", "legal", "privacy", "data"),
        cadence=(
            "Two level sentences at most, never raising the register. "
            "States the exposure, stops, then asks who owns it. No "
            "emphasis, no hedging, no hurry."
        ),
        voice=Voice.DRY,
        unheard=(
            'We have no audio from your end at present.',
            'Nothing has reached us since we began.',
        ),
        nudges=(
            'Still present?',
            'The clock is running.',
            'Anybody there?',
        ),
        openers=(
            'Proceed.',
            "When you're ready. I'll be taking notes.",
            "Go on. I'll flag anything that concerns me.",
        ),
        reentries=(
            'The connection dropped. Resume where you stopped.',
            'We lost audio for a period. Continue.',
        ),
    ),
)


#: The archetypes a session gets when nobody has chosen.
#:
#: **Mixed, not uniformly hostile** (`CLAUDE.md`): a champion, a skeptic and a
#: neutral. A room where every voice is against you is not a harder room, it is a
#: less informative one — there is nothing to lose and nothing to win, and Open
#: Risk #1 is already that people may not tolerate being attacked at all.
#:
#: Three, because the constraint is the session rather than the cost. Only one
#: archetype speaks per turn, so a larger panel is nearly free — but a ten-minute
#: interrogation split six ways gives everybody two questions and nobody a line
#: of attack that goes anywhere. Depth is what makes the room worth sitting in.
DEFAULT_PANEL: tuple[Archetype, ...] = tuple(
    archetype
    for archetype in LIBRARY
    if archetype.name in {"cfo", "technical_skeptic", "champion"}
)


def by_name(name: str) -> Archetype | None:
    """One archetype from the library, or nothing.

    **Refuses a name a user owns rather than answering "nothing".** Rows carry
    the `custom:` prefix (`docs/custom-archetypes.md` §5) and this function
    cannot resolve one — but `assemble()` turns `None` into `ArchetypeNotFound`,
    so returning it would report a panelist that exists to its own author as a
    name nobody answers to. It is a defect in the caller, which forgot to load
    the row, and it is raised as one.

    It is also the guard that keeps two authorities out of one namespace. Doing
    it here rather than at each call site is deliberate: this codebase has twice
    shipped a collision that nothing reported — `retention` claimed by two
    archetypes so the Risk Officer's `data` domain silently never fired, and
    `vocabulary.ts` mapping `distracted` against a server shipping
    `distracted_executive`. Both were namespaces without a guard.
    """
    if name.startswith(_AUTHORED_PREFIX):
        raise ValueError(
            f"{name!r} names a row, not a shipped archetype — load it and pass "
            "it in rather than looking it up here"
        )

    for archetype in LIBRARY:
        if archetype.name == name:
            return archetype
    return None


#: Duplicated from `agents/authored.CUSTOM_PREFIX`, and deliberately.
#:
#: `authored` imports `Archetype` from this module, so importing it back would
#: be a cycle. A four-character constant repeated once, with a test pinning the
#: two together, is cheaper than restructuring the module boundary to avoid it.
_AUTHORED_PREFIX = "custom:"
