import type { PastRoom } from '../api/sessionsApi';

/**
 * What we still hold of this account's rooms.
 *
 * A retention figure, not a history one, and the distinction is the reason this
 * is a function rather than `rooms.length` at the call site. The Library lists
 * every room ever run; Settings answers "what do you hold", and a room whose
 * recording has expired is one we no longer hold anything audible of.
 *
 * Derived on the client from a list the screen already fetches, rather than
 * from a count endpoint. Two things make that the right side of the line: the
 * list is scoped to the caller by the server, so no authorisation lives here,
 * and the rule — held means the audio is still there — is the same rule the
 * Library already draws each row with.
 */

export interface SavedRooms {
  rooms: number;
  /** When the earliest-expiring recording stops being playable. */
  oldestExpiry: Date | null;
}

export function saved(rooms: PastRoom[]): SavedRooms {
  const held = rooms.filter((room) => room.recording.state === 'available');

  const expiries = held
    .map((room) => room.recording.expiresAt)
    .filter((at): at is string => at !== null)
    .map((at) => new Date(at).getTime());

  return {
    rooms: held.length,
    // `Math.min` of nothing is `Infinity`, which would become an invalid Date
    // and render as "Invalid Date" on the one screen that must not guess.
    oldestExpiry: expiries.length === 0 ? null : new Date(Math.min(...expiries)),
  };
}
