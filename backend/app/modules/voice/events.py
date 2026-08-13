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


#: The union upstream code matches on. It grows as the relay learns to handle
#: more, rather than being written out in advance against events nothing yet
#: reacts to.
VoiceEvent = ChannelReady | UserSpoke | Heartbeat | AgentAudio
