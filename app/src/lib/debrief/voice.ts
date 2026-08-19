import { createPlayback, type PlaybackContext } from '../voice/playback';

/**
 * The coach, out loud.
 *
 * Built on the room's own `createPlayback` rather than beside it, because the
 * two are the same problem: the same synthesiser, at the same 16 kHz, into the
 * same hardware rate that is 48 kHz on every Android phone we have touched.
 * Everything that module learned on a device — resample before the buffer is
 * built, claim back the six decibels ElevenLabs leaves on the table — applies
 * here unchanged, and a second copy would be a second place to learn it.
 *
 * What differs is the shape of a turn. The room streams frames and can be
 * interrupted mid-word; a coaching reply arrives whole, in one JSON field, and
 * nobody barges in on it. So this owns exactly two things the room does not:
 * decoding base64, and the rule that a new reply silences the one before it.
 */

export interface CoachVoice {
  /** Speak one reply, base64 PCM16 at the wire rate. */
  play(speech: string): void;
  /**
   * Cut the reply off now, and stay able to speak.
   *
   * For the moment the microphone opens. The coach comes out of the same phone
   * that is about to record, so a reply still playing would be recorded,
   * transcribed and sent back as though the presenter had said it.
   */
  silence(): void;
  /** Leaving the screen. Audio offered after this is dropped. */
  stop(): void;
}

export interface CoachVoiceOptions {
  context: PlaybackContext;
}

export function createCoachVoice({ context }: CoachVoiceOptions): CoachVoice {
  const playback = createPlayback({ context });

  return {
    play: (speech) => {
      // A reply with no audio in it is not reachable through a healthy server:
      // `coaching._voice` raises rather than returning silence. Which is why it
      // is guarded — when it does happen something has already gone wrong, and
      // a zero-length native buffer would make that a second failure on top of
      // a sheet the user is still working through.
      if (speech.length === 0) {
        return;
      }

      // The room's barge-in, borrowed for a different reason. There nobody is
      // interrupting the coach — but a follow-up asked while the last answer is
      // still coming out would put two coach voices on one speaker, which is
      // not a room, it is a fault. A reply supersedes the one it answers past.
      playback.discard();
      playback.enqueue(decode(speech));
    },
    silence: () => playback.discard(),
    stop: () => playback.stop(),
  };
}

/**
 * Base64 to bytes, without a dependency.
 *
 * `atob` is on Hermes and `Buffer` is not — the same finding `auth/session.ts`
 * records for reading a JWT payload, and the same reason not to reach for a
 * polyfill to undo one encoding.
 */
function decode(speech: string): ArrayBuffer {
  const binary = atob(speech);
  const bytes = new Uint8Array(binary.length);

  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }

  return bytes.buffer;
}
