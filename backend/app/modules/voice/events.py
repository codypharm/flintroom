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
    """

    text: str


@dataclass(frozen=True, slots=True)
class Interrupted:
    """The user talked over a panelist, and the panelist stopped.

    Barge-in is the feature the voice provider was chosen for (Product.md
    §5.1) — panelists interrupt the way real rooms do, and can be interrupted
    back. The provider handles its own half; this is the notification that it
    happened, and what it obliges *us* to do is drop the audio already in
    flight to the phone.
    """


#: The union upstream code matches on. It grows as the relay learns to handle
#: more, rather than being written out in advance against events nothing yet
#: reacts to.
VoiceEvent = (
    ChannelReady | UserSpoke | Heartbeat | AgentAudio | AgentTranscript | Interrupted
)


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
