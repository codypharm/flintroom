"""What a voice provider tells us — in our vocabulary, never theirs.

The whole point of this file is that no other module learns a vendor's event
names. ElevenLabs says `conversation_initiation_metadata`, `vad_score`,
`user_transcript`, `ping`; Gemini Live says something else; the relay reads
neither. Translation happens once, inside the adapter for that provider, and
everything upstream sees the events below.

Without this the "voice provider behind an interface" decision (CLAUDE.md →
Architecture Decisions) would be decorative: the interface would exist, and
swapping the provider would still mean editing the relay.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class ChannelReady:
    """The provider has a live channel. From here the meter may run.

    Not the same moment as opening a session. A session sits in `provisioning`
    while agent spin-up runs, which takes real time and can fail before any
    audio exists — so this is what separates a room that opened from one that
    never did.
    """


@dataclass(frozen=True, slots=True)
class UserSpoke:
    """The person in the room said something.

    Only the *user*. A panelist talking is not this event, and must never be
    reported as one: a room where the agents monologue at nobody is exactly the
    expensive failure the idle timeout exists to catch, and an adapter that
    conflated the two would disarm it.

    Carries no confidence score. ElevenLabs reports `vad_score` as a 0–1
    double, and deciding what counts as speech is left inside that adapter
    until something upstream actually needs to weigh it — an event carrying a
    number nothing reads is a field that quietly goes wrong.
    """


@dataclass(frozen=True, slots=True)
class Heartbeat:
    """The channel is still delivering.

    Says nothing about whether anyone is participating — that is `UserSpoke`,
    and the two clocks they feed are deliberately separate. A room can be
    healthy and abandoned at the same time, and it ends under a different
    reason depending on which one ran out.
    """


@dataclass(frozen=True, slots=True)
class AgentAudio:
    """A panelist speaking, as PCM16 the client can play directly.

    Already decoded from whatever the provider put on the wire — ElevenLabs
    sends base64, and stripping that is the adapter's job, not the relay's.
    What reaches here is what reaches the phone, byte for byte.
    """

    pcm: bytes


@dataclass(frozen=True, slots=True)
class AgentTranscript:
    """A panelist speaking, as words — the same utterance as `AgentAudio`.

    Carried because captions are in the v1 accessibility floor (CLAUDE.md), not
    because anything server-side reads them: a voice-only interrogation is
    unusable to a deaf or hard-of-hearing user without them, and the live
    interrogation surface makes this line its primary content for *every* user,
    since a glancing presenter reads the question they just missed.

    A finished utterance rather than a token stream. Providers differ on that —
    ElevenLabs sends one `agent_response` per turn — so the wire carries whole
    lines and any word-by-word emergence is the client's animation. An event
    that sometimes meant a fragment and sometimes a line would push that
    ambiguity into every consumer.

    Deliberately only the panel. Whether the user's own speech is captioned back
    to them is an open product question on that surface, recommended against —
    it invites reading yourself instead of arguing — so there is no event for it
    and adding one is a decision, not a completion.

    Never logged. `CLAUDE.md` forbids transcript text in logs, and unlike a
    secret it cannot be caught by key-name redaction, so it must not be passed
    to a log call at all.

    `speaker` travels with the words rather than in a frame of its own. One
    utterance is one caption, and a name arriving separately from the line it
    belongs to would be a synchronisation problem invented for nothing. The
    live screen draws one tray per seated archetype and develops whoever holds
    the floor (`Product.md` §3.4), which it cannot do from text alone.
    """

    text: str
    #: The archetype's name, as `Session.archetypes` and the transcript's own
    #: `speaker` column spell it — so the phone can match a caption to a seat
    #: without a second vocabulary.
    speaker: str


@dataclass(frozen=True, slots=True)
class Interrupted:
    """The user talked over a panelist, and the panelist stopped.

    Barge-in is the feature the voice provider was chosen for (Product.md
    §5.1) — panelists interrupt the way real rooms do, and can be interrupted
    back. The provider handles its own half; this is the notification that it
    happened, and what it obliges *us* to do is drop the audio already in
    flight to the phone.
    """


@dataclass(frozen=True, slots=True)
class AgentFinished:
    """The panel is done, and the floor is the presenter's again.

    The room strictly alternates — one panel turn per finished utterance, with
    a dispute being how a turn is *framed* rather than a second turn queued
    behind it — so a panelist stopping really does hand the floor back.

    Carried rather than inferred. Nothing else on the wire marks where an
    utterance ends: the caption arrives *before* its audio, and audio is just
    frames that stop. A phone left to guess would watch for a gap in arrivals
    or a drained playback buffer, and both are guesses about the network. A
    two-second stall would invite the presenter to speak over the end of a
    question, they would take it, the panelist would resume, and the room would
    have manufactured an accidental barge-in — which reads as broken at exactly
    the moment it is supposed to feel real.

    Emitted after the last frame, never before: a floor announced ahead of the
    sound it follows is the same invitation to talk over the question.

    **Not emitted when barge-in cancels the turn.** The presenter already holds
    the floor by having taken it, and handing somebody something they are
    standing on reads as a room that has lost track. `Interrupted` is that
    case, and it says so already.
    """


#: The union upstream code matches on. It grows as the relay learns to handle
#: more, rather than being written out in advance against events nothing yet
#: reacts to.

class Attention(StrEnum):
    """What the room is doing with the floor, while the floor is the presenter's.

    Five things look identical to somebody sitting in a room that has gone
    quiet — it is thinking, it did not hear them, it is waiting for more, it has
    failed, or it is about to end — and after a day of testing the architect
    reported the middle of that list as the panel being broken. These values
    separate the ones that cost a session.

    "It did not hear them" split in two once #77 was measured. A final that
    never arrived and a *microphone* that never delivered anything are different
    failures with different remedies — say it again, against check the phone —
    and `LISTENING` was quietly claiming both.

    **Only the server can answer this.** A final arriving is invisible to the
    phone, so no timer on the device can tell "composing" from "never heard
    you"; it can only guess, and it would guess wrong in exactly the case that
    matters.

    Deliberately silent about a panelist speaking. The caption and
    `turn_finished` already carry that, and a second source for one fact is the
    bug that took a panelist off the screen mid-sentence this morning.
    """

    #: Nothing of theirs is outstanding. The sound bar already says this, so the
    #: screen shows no words for it.
    LISTENING = "listening"

    #: We have an utterance and are not answering yet — the opening floor (#79)
    #: letting somebody finish making their case.
    HEARD = "heard"

    #: A turn is in flight. Composing, or synthesising, or streaming.
    WORKING = "working"

    #: Nothing has reached the room since it opened. #77.
    #:
    #: **Never once**, which is a different claim from "not right now" and the
    #: only one that can honestly be made. `docs/echo-cancellation.md` measured
    #: a quiet room on the configuration this product ships reading exact
    #: digital zero — noise suppression gates it — so an ordinary pause and an
    #: unplugged microphone are byte-for-byte identical. A room that has heard
    #: a voice once can never send this again, which is what makes it safe to
    #: show at all.
    #:
    #: **Shown, not spoken, and that half is still open.** #24 decided the
    #: opposite for the idle nudge — a seated panelist asks out loud at sixty
    #: seconds — and `agents/silence.py` names "holding a dead microphone" as
    #: one of the three people it is for. This shipped visual-only on the
    #: argument that a dead-microphone presenter has been *talking* and is
    #: present, where the nudge's user has walked away; a room that speaks to
    #: somebody sitting right there says it twice.
    #:
    #: That argument was the agent's and the architect has not ruled on it.
    #: It is recorded here rather than in a task because #77 is closed, and an
    #: open question with nowhere to live stops being a question.
    UNHEARD = "unheard"


@dataclass(frozen=True, slots=True)
class Attending:
    """The room reporting what it is doing, so the phone never has to infer it.

    **Derived at the moment of sending, never stored.** A remembered state is
    stranded by the paths that fail: a turn that dies would leave the room
    claiming to be working for the rest of the session, which is worse than the
    silence it replaced because it is confidently wrong. Computed, there is no
    transition to miss and nothing to clear.

    Sent on the moments that matter for speed, and on every heartbeat for
    correctness — the heartbeat repeats it even when nothing changed, because
    suppressing that would leave a phone which dropped one message wrong for
    the rest of the room.
    """

    state: Attention

@dataclass(frozen=True, slots=True)
class Spent:
    """What one turn cost, in the units the providers bill in.

    An event rather than a return value because the channel has no database and
    no session id — deliberately. Everything it knows is the conversation; every
    write belongs to the relay. That separation is what lets the same channel be
    driven by a test with no database at all.

    Reported per turn rather than accumulated to the end of the room. A session
    whose process dies is settled later by the reaper, which never held the
    channel, so anything kept in memory would be lost exactly for the rooms
    where cost and revenue diverge most — the ones we paid three vendors for and
    then refunded.

    Every field is what a provider actually charges for, which is why they are
    four different units. `CLAUDE.md` makes cost instrumentation a required task
    rather than a later addition, and Open Risk #4 says every margin in §4.4
    rests on an unverified $0.12/min that nothing in the system could currently
    contradict.
    """

    #: Audio the transcriber processed. ElevenLabs Scribe bills by the hour.
    stt_seconds: int = 0

    #: The panel model's prompt and reply, summed over routing and composition.
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0

    #: Characters handed to synthesis. **Not** a function of room length —
    #: text-to-speech is billed per character, so a talkative panel costs more
    #: than a terse one for the same minute. It is the one vendor whose bill the
    #: 25-word limit directly controls.
    tts_characters: int = 0


#: Everything a channel may say. Named after the classes rather than before
#: them, because the union has to sit below every member and `Spent` and
#: `Attending` are declared last.
#:
#: `Spent` was missing until 2026-08-19 — handled by the relay and absent here,
#: which nothing caught because this project runs no type checker. Worth knowing
#: that this union is documentation with teeth only if somebody points a checker
#: at it.
VoiceEvent = (
    ChannelReady
    | UserSpoke
    | Heartbeat
    | AgentAudio
    | AgentTranscript
    | AgentFinished
    | Interrupted
    | Attending
    | Spent
)
