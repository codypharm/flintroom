# The Voice Stream Protocol

What travels on `WS /v1/sessions/{session_id}/stream`.

This lives here rather than in `contracts/openapi.yaml` because OpenAPI does not
describe WebSockets. The contract still covers everything that opens this socket
— `POST /v1/sessions` and the `stream_ticket` it returns — so the generated
client can reach the door; what happens after the handshake is written down here
instead.

## Shape

```
Expo  ──[binary: PCM16 16kHz mono]──►  FastAPI  ──[base64 PCM]──►  ElevenLabs
Expo  ◄──[binary: PCM16 16kHz mono]──  FastAPI  ◄──[base64 PCM]──  ElevenLabs
Expo  ◄──[text: JSON control]────────  FastAPI
```

The relay transcodes nothing. PCM throughout is what keeps a decode out of the
latency path (Open Risk #3), and base64 is applied only on the provider leg
because that is their wire requirement, not ours — paying its 33% expansion on
the phone's uplink would be bandwidth spent for nothing.

## Connecting

1. `POST /v1/sessions` → `201` with a session and a `stream_ticket`.
2. Connect to `/v1/sessions/{id}/stream?ticket=<stream_ticket>` within **30
   seconds**. The ticket is single-use and bound to that one session.
3. The server redeems the ticket *before* accepting. An unauthorised caller
   never reaches an open socket.

The ticket rather than a bearer header because a browser cannot set headers on a
WebSocket handshake, and `CLAUDE.md` forbids mobile-only assumptions a web client
would later have to unpick. Everything about the ticket's design follows from the
fact that query strings land in access logs: single-use, seconds-long, and worth
exactly one room.

## Frames

| Direction | Type | Meaning |
| --- | --- | --- |
| client → server | binary | User audio. PCM16, 16 kHz, mono. |
| server → client | binary | Panel audio. Same format. Play as received. |
| server → client | text | Control. JSON, `{"type": ...}`. |

Control messages are a separate frame type on purpose: the client never has to
inspect a payload to know whether it is holding audio or an instruction.

### Control messages

| `type` | Payload | Client must |
| --- | --- | --- |
| `discard_playback` | — | Drop everything buffered and unplayed, immediately. |
| `transcript` | `text`, `speaker` | Show this as the panel's current line, from that archetype. |
| `turn_finished` | — | The panel is done. The floor is the presenter's. |
| `attending` | `state` | What the room is doing while the floor is the presenter's: `listening`, `heard`, `working`, `unheard`. |

`discard_playback` is barge-in. Audio runs ahead of playback, so when the user
talks over a panelist the device is still holding frames of a sentence that will
never be finished. Playing them out is the room failing to be interruptible,
which is the feature the voice provider was chosen for (`Product.md` §5.1).

`transcript` is the caption, and it is an accessibility requirement rather than
a convenience: `CLAUDE.md` puts live captions for panel speech in the v1 floor,
because a voice-only interrogation offers a deaf or hard-of-hearing user nothing
at all. It is also the interrogation screen's primary content for every user — a
presenter glancing down reads the question they just missed.

It arrives as a **whole utterance**, not a token stream, and it is the caption
for audio the client is already playing. Any word-by-word emergence is the
client's animation; the wire carries finished lines. A provider that revises an
utterance after the fact is ignored — by the time a correction lands the line has
been spoken aloud, and retracting it would be the room contradicting itself.

`speaker` is the archetype's name as `POST /v1/sessions` returned it in
`archetypes`, and as the stored transcript spells it — one vocabulary, so the
phone can match a caption to a seat without translating. The live interrogation
surface draws one tray per seated archetype and develops whoever holds the
floor (`Product.md` §3.4), which it cannot do from text alone. It travels
inside the caption rather than on a frame of its own because one utterance is
one caption, and a name arriving separately from its line would be a
synchronisation problem invented for nothing.

`attending` exists because **five things look like silence** to somebody in a
room that has gone quiet: it is thinking, it did not hear them, it is waiting
for more, it has failed, or it is about to end. This message tells apart the
ones that cost a room, and only the server can tell them apart at all — a final
arriving is invisible to the phone, so any timer on the device would be racing
the network and would be wrong in exactly the case that matters.

**"It did not hear them" turned out to be two things**, and `unheard` is the
second — #77. A final that never arrived wants the sentence said again; a
microphone that has never delivered anything wants the phone checked. Those are
different remedies, and `listening` was quietly claiming both.

The obvious way to answer it does not work. `docs/echo-cancellation.md` measured
the audio configuration this product actually ships — patched
`Usage::VoiceCommunication` on both streams, `MODE_IN_COMMUNICATION`,
loudspeaker — and found a *quiet room* on a real S24+ reading exact digital
zero, every sample, peak -120 dBFS. Noise suppression gates the room outright.
The doc states the consequence: "perfect cancellation and a dead microphone are
indistinguishable in it." So on Android an ordinary pause and an unplugged
microphone are byte-for-byte the same, no level on the device separates them,
and any warning built on one would fire on the other.

What *is* separable is a room that has **never once** heard anything, and that
is exactly what `unheard` claims. A working microphone delivers a non-zero
sample the moment somebody speaks; a dead one never does. It is a latch rather
than a reading: it can only fire before the first real audio, and the first
voice turns it off for the rest of the room. That is what makes it safe to show
at all — nothing that could interrupt a presenter mid-thought.

It goes out after twenty-five seconds of forwarded audio with nothing in it,
bounded on both sides by measurements. Above, the transcriber commits an empty
utterance after 36-37 seconds of digital silence (#77, three rooms), and the
room drops that final rather than answering it — so past that point the
presenter's only signal is a room that never speaks. Below,
`NUDGE_AFTER_SECONDS` is 60 and argues quiet is still plausibly thought beneath
it. The escalation reads: **25s** the screen says so, **~37s** the transcriber
invents an utterance and `_listen` discards it, **60s** a panelist asks out
loud, **90s** `IDLE_LIMIT` ends the room and refunds it.

The wording states our side and never diagnoses theirs — *"Nothing has reached
us yet — check your microphone."* A presenter who has simply not started yet
produces the same bytes as one holding a dead handset, so a message claiming the
microphone is broken would be false for half the people who see it. This
codebase has already shipped a warning that fired at the wrong moment once —
`app/src/lib/audio/hearing.ts` told the architect the room could barely hear
them, continuously, while they were saying nothing — and the lesson recorded
there is that a warning firing at the wrong time teaches people to ignore the
one that matters.

It says nothing about a panelist speaking. The caption and `turn_finished`
already carry that, and a second source for one fact is what took a speaking
panelist off the screen mid-sentence.

**Sent on transitions for speed and on every heartbeat for correctness**, and
the heartbeat repeats it even when nothing has changed. Suppressing the repeat
would leave a phone that dropped one message wrong for the rest of the room.
The value is derived at the moment of sending rather than stored, so no path
that fails can strand it: a turn that dies cannot leave the room claiming to be
working, because nothing is remembering that it was.

A client that does not recognise a value must keep showing the last one it
understood. More values are expected — the idle warning is queued behind this.

The fifth thing that looks like silence — the room being about to end — is
**not** an `attending` value and deliberately so. It is spoken: a seated
panelist asks whether anybody is there at sixty seconds, against an
`IDLE_LIMIT` of ninety. The phone is face-up on a desk and the person this
exists for has turned away, left, or is holding a dead microphone, so a visual
warning would arrive at the moment attention is lowest aimed at somebody who by
definition stopped looking.

It needs no new message: the line goes out as an ordinary `transcript` plus
audio plus `turn_finished`, because a panelist really did speak. The caption is
its own visual rendering, for free, and the two can never disagree.

It changes nothing about the clock. Asking does not reset the idle timer or
extend the limit — panel speech never counts as activity, precisely so a room
talking to an empty chair still ends. A warning that bought time would be a
second clock, and a silent room could then run forever.

**Which question it asks depends on `unheard`**, and that was a live bug until
#77. Every hand-written nudge asks the presenter to *speak* — "take your time,
but say something", "come on, talk to me" — and nothing consulted whether the
room had ever heard anything before choosing one. So the third person in the
list above, the one holding a dead microphone, was told at sixty seconds to do
the exact thing that had already failed for a minute. That reads as a room which
is not listening, which is worse than saying nothing.

A room that has heard nothing now draws from a second hand-written set that
sends them to the handset instead — *"Nothing is coming through."*, *"We have no
audio from your end at present."* Same channel, same constraints, opposite
instruction. The screen still carries the actionable half at twenty-five
seconds; this is what reaches somebody who is not looking at it.

`turn_finished` says the panel has stopped and is waiting. **It is carried
rather than inferred, and that is the whole reason it exists.** Nothing else
marks where an utterance ends: the caption arrives *before* its audio, and
audio is frames that simply stop. A client left to guess would watch for a gap
in arrivals or a drained playback buffer, and both are guesses about the
network — a two-second stall would tell the presenter to speak while a panelist
is still mid-question, they would take the floor, the panelist would resume,
and the room would have manufactured an accidental barge-in.

It arrives **after** the last frame of the utterance, never before. A floor
announced ahead of the sound it follows is the same invitation to talk over the
end of the question.

It is **not** sent when barge-in cuts a turn short. The presenter already holds
the floor by having taken it, and `discard_playback` has already said so;
handing somebody something they are standing on reads as a room that has lost
track of who is speaking.

**Only the panel is captioned.** The user's own speech is deliberately not sent
back to them; whether it ever should be is an open product question, currently
recommended against, because reading yourself invites editing instead of arguing.

Text frames from the client are currently ignored rather than refused, so that a
control message added later cannot kill a live room by arriving before the server
knows what it means.

## Close codes

| Code | Meaning | Client should |
| --- | --- | --- |
| `1000` | The room ended normally. | Go to the debrief. |
| `4401` | Ticket invalid, expired, spent, or for another room. | Re-`POST /v1/sessions`. |
| `4502` | The room ended on an upstream failure. | Go to the debrief. |

`4401` is deliberately identical for every refusal. Distinguishing expired from
spent from wrong-room would let a caller holding a string it should not have
learn something by presenting it — the same silence the HTTP layer keeps by
answering 404 rather than 403 for a session somebody else owns.

`4502` never names the provider. The vendor is an implementation detail that goes
stale the moment it is swapped, which the architecture is built to allow.

**Any close is an ending, not an error.** Minutes are charged in arrears, so a
dropped connection leaves the ledger already correct and nothing is owed back. A
room that broke upstream is refunded in full, automatically, before the socket
closes. The client never has to reconcile anything.

## What the client must not assume

- **Silence is not the end.** A user thinking about a hostile question is still
  in the room. The server decides abandonment, via the idle timeout.
- **There is no warning before that.** The room simply ends and refunds in full.
  A warning is wanted and deliberately unbuilt: the right channel for a phone
  lying face-up on a desk is probably a panelist asking whether you are still
  there, not a banner on a screen nobody is looking at — and that is panel tone,
  which belongs with the archetype work in Phase 3. Building the visual version
  first would mean shipping the weaker answer and then living with it.
- **There is no heartbeat to send.** The server holds the provider connection and
  already knows whether audio is flowing. A client-side keepalive would be a
  second answer to a question that already has one — and, being unremovable from
  shipped mobile builds, would outlive its own purpose by years.
- **The socket does not report balance.** Running out mid-room never interrupts
  an interrogation (`Product.md` §4.5); the room finishes and settles.
