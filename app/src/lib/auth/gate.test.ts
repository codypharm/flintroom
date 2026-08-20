import { whoIsThere } from './gate';
import { SignedOut } from './session';

/**
 * What a launch is allowed to conclude, and from what.
 *
 * Pure, and separate from the hook that calls it, because the whole risk here
 * is in the mapping rather than in the plumbing: three of these four answers
 * send somebody to a different screen, and one of them ends their session.
 */

it('lets somebody straight in when the credential is good and the room is described', async () => {
  const seen = await whoIsThere(async () => ({ userId: 'u-1', onboarded: true }));

  expect(seen).toBe('ready');
});

it('asks about the room when the account has never described one', async () => {
  // The reordering: sign-in first, survey after. An account can exist with no
  // configuration now, on purpose, and this is the state that gets it asked.
  const seen = await whoIsThere(async () => ({ userId: 'u-1', onboarded: false }));

  expect(seen).toBe('undescribed');
});

it('sends somebody to sign in when the credential is gone', async () => {
  const seen = await whoIsThere(async () => {
    throw new SignedOut('no stored credentials');
  });

  expect(seen).toBe('signed out');
});

it('never signs somebody out because the server was unreachable', async () => {
  // The failure that matters most. A phone loses its connection constantly,
  // and a gate that read that as a dead credential would throw away a working
  // session — including the refresh token, which cannot be got back.
  const seen = await whoIsThere(async () => {
    throw new Error('network request failed');
  });

  expect(seen).toBe('unreachable');
});
