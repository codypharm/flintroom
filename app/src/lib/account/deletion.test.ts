import { SignedOut } from '../auth/session';
import {
  CANCELLED_ON_SIGN_IN,
  confirmDeletion,
  NOT_SIGNED_IN,
  scheduledMessage,
} from './deletion';

/**
 * Asking to be forgotten, from the phone.
 *
 * The endpoint is proved in the backend suite; what is proved here is the
 * shape of the moment around it, which is where this can go wrong in ways no
 * server test would see: destroying an account nobody confirmed, or destroying
 * one and leaving the app looking signed in.
 *
 * Plain TypeScript with the alert and the API injected. `CLAUDE.md` keeps pure
 * logic off the renderer, and the confirmation is a sequence rather than a
 * view — a test that mounted a screen to assert an order of operations would
 * be slower and would prove less.
 */
const PURGE_AT = new Date('2026-08-25T09:00:00Z');

function flow(overrides: Partial<Parameters<typeof confirmDeletion>[0]> = {}) {
  const told: string[] = [];

  const calls = {
    deleted: 0,
    forgotten: 0,
    told,
  };

  const run = () =>
    confirmDeletion({
      ask: async () => true,
      deleteAccount: async () => {
        calls.deleted += 1;
        return PURGE_AT;
      },
      forgetCredentials: async () => {
        calls.forgotten += 1;
      },
      tell: async (message) => {
        told.push(message);
      },
      ...overrides,
    });

  return { run, calls };
}

it('destroys nothing until the person says yes twice', async () => {
  // The button is the first yes; `ask` is the second. A single tap on a
  // destructive control at the bottom of a scrolling screen is not consent,
  // and this one cannot be undone after seven days.
  const { run, calls } = flow({ ask: async () => false });

  await run();

  expect(calls.deleted).toBe(0);
  expect(calls.told).toEqual([]);
});

it('tells them the date rather than only that it worked', async () => {
  // The window is recoverable and signing in is how it is recovered, so a
  // confirmation that omits the date withholds the only thing that makes the
  // window usable.
  const { run, calls } = flow();

  await run();

  expect(calls.deleted).toBe(1);
  expect(calls.told).toHaveLength(1);
  expect(calls.told[0]).toContain('25 August');
  expect(calls.told[0]).toContain('signing in');
});

it('forgets the stored credentials, because the server already has', async () => {
  // The request revokes every refresh token server-side. An app still holding
  // the pair would look signed in, fail its next call with a 401, and present
  // that as an error rather than as the deletion the person just asked for.
  const { run, calls } = flow();

  await run();

  expect(calls.forgotten).toBe(1);
});

it('keeps the session when the request fails', async () => {
  // Nothing was scheduled, so signing the user out would strand them: the
  // account is alive, they now cannot reach it, and the app told them nothing
  // about which of the two happened.
  const { run, calls } = flow({
    deleteAccount: async () => {
      throw new Error('offline');
    },
  });

  await run();

  expect(calls.forgotten).toBe(0);
  expect(calls.told[0]).toContain('not');
});

it('tells a signed-out caller to sign in rather than to try again', async () => {
  // The refusal that "try again in a moment" is wrong for. A revoked session —
  // signed out on another device, or the family reused — fails identically on
  // every retry, so the message has to name the thing that would actually fix
  // it. The credentials are cleared because the server has already stopped
  // honouring them.
  const { run, calls } = flow({
    deleteAccount: async () => {
      throw new SignedOut('refused by DELETE /v1/me');
    },
  });

  await run();

  expect(calls.told).toEqual([NOT_SIGNED_IN]);
  expect(calls.deleted).toBe(0);
});

it('says out loud when signing in has called a deletion off', async () => {
  // `docs/account-deletion.md` decision 5, and the message is the load-bearing
  // half: an account that quietly un-deletes itself is worse than one that
  // stayed deleted, because the user never learns their data is still there.
  expect(CANCELLED_ON_SIGN_IN).toContain('cancelled');
  expect(CANCELLED_ON_SIGN_IN.toLowerCase()).toContain('signing in');
});

it('writes the date the way a person reads one', () => {
  // "25 August", not a countdown and not an ISO string. The same rule the
  // settings screen already follows for retention: a date is a fact, a clock
  // running down is pressure nobody asked for.
  expect(scheduledMessage(PURGE_AT)).toContain('25 August');
  expect(scheduledMessage(PURGE_AT)).not.toContain('2026-08-25');
});
