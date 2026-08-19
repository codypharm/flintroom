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
