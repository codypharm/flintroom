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

| `type` | Client must |
| --- | --- |
| `discard_playback` | Drop everything buffered and unplayed, immediately. |

`discard_playback` is barge-in. Audio runs ahead of playback, so when the user
talks over a panelist the device is still holding frames of a sentence that will
never be finished. Playing them out is the room failing to be interruptible,
which is the feature the voice provider was chosen for (`Product.md` §5.1).

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
- **There is no heartbeat to send.** The server holds the provider connection and
  already knows whether audio is flowing. A client-side keepalive would be a
  second answer to a question that already has one — and, being unremovable from
  shipped mobile builds, would outlive its own purpose by years.
- **The socket does not report balance.** Running out mid-room never interrupts
  an interrogation (`Product.md` §4.5); the room finishes and settles.
