import { CancelledByUser } from './provider';

/**
 * Google, behind the interface the rest of the app already talks to.
 *
 * The SDK is mocked rather than run, and the reason is what these tests are
 * *for*: none of them is about whether Google works. They are about the three
 * ways this adapter can be wrong in a way nothing else notices — a cancel
 * reported as a failure, a missing token returned as a token, and the wrong
 * client ID handed to `configure`, which is the mistake that already cost a day
 * on the server side.
 */

const mockSignIn = jest.fn();
const mockConfigure = jest.fn();
const mockHasPlayServices = jest.fn();

/**
 * The SDK's own session, which is not ours.
 *
 * Cleared before every sign-in so the account chooser actually appears. Named
 * `mockSdkSignOut` rather than `mockSignOut` because `auth.signOut()` is a
 * different thing entirely — one ends a Flintroom session, the other forgets
 * which Google account a phone used last.
 */
const mockSdkSignOut = jest.fn();

jest.mock('@react-native-google-signin/google-signin', () => ({
  GoogleSignin: {
    configure: (...args: unknown[]) => mockConfigure(...args),
    signIn: (...args: unknown[]) => mockSignIn(...args),
    hasPlayServices: (...args: unknown[]) => mockHasPlayServices(...args),
    signOut: (...args: unknown[]) => mockSdkSignOut(...args),
  },
  statusCodes: { SIGN_IN_CANCELLED: 'SIGN_IN_CANCELLED' },
}));

beforeEach(() => {
  jest.resetModules();
  mockSignIn.mockReset();
  mockConfigure.mockReset();
  mockHasPlayServices.mockReset().mockResolvedValue(true);
  mockSdkSignOut.mockReset().mockResolvedValue(undefined);
});

function google(env: Record<string, string | undefined> = {}) {
  process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID = 'web.example';
  process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID = 'ios.example';

  for (const [name, value] of Object.entries(env)) {
    // Deleted rather than assigned undefined: `process.env` coerces, so
    // assigning would set the literal string "undefined" and the guard under
    // test would happily accept it as configured.
    if (value === undefined) delete process.env[name];
    else process.env[name] = value;
  }

  // `require` rather than a dynamic import, which this runner has no ESM loader
  // for. Re-required after `resetModules` so each test sees `configure` run
  // afresh against its own environment.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  return (require('./google') as typeof import('./google')).createGoogleProvider();
}

describe('the Google provider', () => {
  it('hands back the id token the SDK vouched for', async () => {
    mockSignIn.mockResolvedValue({ data: { idToken: 'token-from-google' } });

    await expect(google().signIn()).resolves.toBe('token-from-google');
  });

  it('configures with the WEB client id, which is what the server verifies', async () => {
    // The mistake this exists to prevent, found on the server on 2026-08-18:
    // the token's `aud` is whichever client asked for it, so passing the iOS id
    // here would mint tokens the backend refuses — as a 401 that names nothing.
    // `webClientId` is the SDK's own name for "the client ID of type WEB for
    // your server", and it is the one the backend pins.
    google();

    expect(mockConfigure).toHaveBeenCalledWith(
      expect.objectContaining({ webClientId: 'web.example', iosClientId: 'ios.example' })
    );
  });

  it('reports a dismissed sheet as a cancel, not as a failure', async () => {
    // The most common outcome of tapping a sign-in button. Left as a generic
    // error it becomes an alert saying something went wrong, shown immediately
    // after somebody deliberately made nothing happen.
    mockSignIn.mockRejectedValue({ code: 'SIGN_IN_CANCELLED' });

    // Matched by name, not by `instanceof`. `resetModules` gives each test a
    // fresh module registry, so the `CancelledByUser` the provider throws is a
    // different class object from the one imported at the top of this file —
    // and `name` is the thing the class sets explicitly for exactly this kind
    // of identification across a boundary.
    await expect(google().signIn()).rejects.toMatchObject({
      name: new CancelledByUser().name,
    });
  });

  it('refuses a success that carried no token', async () => {
    // The SDK resolves with `data: null` when the flow completes without a
    // credential. Passed on, that is an empty string posted to the server and
    // refused there — a sign-in that fails one round trip later, in a place
    // with no idea why.
    mockSignIn.mockResolvedValue({ data: null });

    await expect(google().signIn()).rejects.toThrow(/no token/i);
  });

  it('refuses to run at all without a web client id', async () => {
    // A release built without the variable would otherwise ship a sign-in
    // button that fails on every tap, in the field, with a server-side 401.
    expect(() => google({ EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID: undefined })).toThrow(
      /EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID/
    );
  });
});


it('makes Google ask which account, every single time', async () => {
  // Reported from a phone: "google automatically logged me in into
  // williamikeji@gmail.com instead of for me to choose". The SDK keeps its own
  // session, so `signIn()` on a device that has signed in before resolves
  // silently with the last account and never shows a picker.
  //
  // That is worse here than an annoyance. Choosing the wrong Google account
  // does not just show the wrong name — it puts somebody into a different
  // Flintroom account, with different rooms and a different balance, and until
  // there was a sign-out control there was no way back out of it.
  mockSignIn.mockResolvedValue({ data: { idToken: 'id-token' } });

  await google().signIn();

  expect(mockSdkSignOut).toHaveBeenCalled();
  expect(mockSdkSignOut.mock.invocationCallOrder[0]).toBeLessThan(
    mockSignIn.mock.invocationCallOrder[0]
  );
});

it('signs in anyway when there was no cached session to clear', async () => {
  // A first launch, and the commonest case. `signOut` rejecting there would be
  // the SDK complaining about the state we were trying to reach.
  mockSdkSignOut.mockRejectedValue(new Error('no user signed in'));
  mockSignIn.mockResolvedValue({ data: { idToken: 'id-token' } });

  await expect(google().signIn()).resolves.toBe('id-token');
});
