import type { PastRoom } from '../api/sessionsApi';
import { saved } from './holdings';

/**
 * What "N rooms saved" counts, and what it must not.
 *
 * Settings led with a constant `rooms: 0` for its whole life, so this is the
 * first time the number has meant anything. It is a *retention* figure rather
 * than a history one: the Library lists every room ever run, and this counts
 * the ones whose audio we still hold.
 */

function room(recording: PastRoom['recording']): PastRoom {
  return {
    id: 'r1',
    rehearsalId: 'r1',
    rehearsalName: null,
    audience: null,
    state: 'settled',
    startedAt: '2026-08-01T10:00:00Z',
    endReason: 'user_ended',
    settledAt: '2026-08-01T10:12:00Z',
    archetypes: ['Margin-Obsessed CFO'],
    materialIds: [],
    difficultyLevel: 2,
    recording,
  };
}

const AVAILABLE = (expiresAt: string) => room({ state: 'available', expiresAt });

it('counts the rooms whose audio is still held, not the rooms ever run', () => {
  // The difference is the whole point of the row. A settled room with an
  // expired recording is still in the Library and is no longer something we
  // hold, and counting it would overstate what we have on somebody.
  const held = saved([
    AVAILABLE('2026-09-16T10:00:00Z'),
    room({ state: 'expired', expiresAt: '2026-07-01T10:00:00Z' }),
    room({ state: 'not_recorded', expiresAt: null }),
  ]);

  expect(held.rooms).toBe(1);
});

it('reports the earliest expiry, which is the one that happens first', () => {
  const held = saved([
    AVAILABLE('2026-09-16T10:00:00Z'),
    AVAILABLE('2026-08-30T10:00:00Z'),
    AVAILABLE('2026-10-02T10:00:00Z'),
  ]);

  expect(held.oldestExpiry).toEqual(new Date('2026-08-30T10:00:00Z'));
});

it('ignores the expiry of a room whose audio is already gone', () => {
  // An expired recording's date is in the past. Letting it win the minimum
  // would put a date behind us on a line that says "the oldest until".
  const held = saved([
    room({ state: 'expired', expiresAt: '2026-07-01T10:00:00Z' }),
    AVAILABLE('2026-09-16T10:00:00Z'),
  ]);

  expect(held.oldestExpiry).toEqual(new Date('2026-09-16T10:00:00Z'));
});

it('says nothing rather than guessing when nothing is held', () => {
  expect(saved([])).toEqual({ rooms: 0, oldestExpiry: null });
  expect(saved([room({ state: 'not_recorded', expiresAt: null })])).toEqual({
    rooms: 0,
    oldestExpiry: null,
  });
});

it('counts a held room that carries no expiry, without inventing one for it', () => {
  // Not a shape the server sends today, and the count is still the honest
  // answer if it ever does: we hold the audio. Only the date is unknown.
  const held = saved([room({ state: 'available', expiresAt: null })]);

  expect(held).toEqual({ rooms: 1, oldestExpiry: null });
});
