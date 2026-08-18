import { CancelledByUser } from './provider';

/**
 * Apple, behind the same interface Google uses.
 *
 * Three failure modes worth a test, and none of them is "does Apple work". A
 * cancel misreported as an error, a credential with no token passed on as one,
 * and an availability probe that throws taking the whole sign-in screen with
 * it — which would leave an Android user unable to reach the Google button.
 */

const mockSignInAsync = jest.fn();
const mockIsAvailableAsync = jest.fn();

jest.mock('expo-apple-authentication', () => ({
  signInAsync: (...args: unknown[]) => mockSignInAsync(...args),
  isAvailableAsync: (...args: unknown[]) => mockIsAvailableAsync(...args),
  AppleAuthenticationScope: { FULL_NAME: 0, EMAIL: 1 },
}));

beforeEach(() => {
  mockSignInAsync.mockReset();
  mockIsAvailableAsync.mockReset();
});

// eslint-disable-next-line @typescript-eslint/no-require-imports
const apple = () => require('./apple') as typeof import('./apple');

describe('the Apple provider', () => {
  it('hands back the identity token Apple vouched for', async () => {
    mockSignInAsync.mockResolvedValue({ identityToken: 'token-from-apple' });

    await expect(apple().createAppleProvider().signIn()).resolves.toBe(
      'token-from-apple'
    );
  });

  it('reports a dismissed sheet as a cancel, not as a failure', async () => {
    mockSignInAsync.mockRejectedValue({ code: 'ERR_REQUEST_CANCELED' });

    await expect(
      apple().createAppleProvider().signIn()
    ).rejects.toMatchObject({ name: new CancelledByUser().name });
  });

  it('refuses a credential that carried no token', async () => {
    // Reachable: `identityToken` is nullable on the credential type. Passed on
    // it becomes an empty body the server refuses a round trip later.
    mockSignInAsync.mockResolvedValue({ identityToken: null });

    await expect(apple().createAppleProvider().signIn()).rejects.toThrow(/no token/i);
  });

  it('reads a thrown availability probe as unavailable', async () => {
    // The gate must never be able to take the screen down. An Android build has
    // no implementation to call, and a throw here would stop the Google button
    // rendering — on the platform where Google is the only way in.
    mockIsAvailableAsync.mockRejectedValue(new Error('no such module'));

    await expect(apple().isAppleAvailable()).resolves.toBe(false);
  });

  it('asks for name and email so the user gets the Hide My Email choice', async () => {
    // Neither value is sent anywhere — the server reads the token's claims. The
    // scopes are requested because the consent sheet is where somebody chooses
    // Hide My Email, and omitting them makes that choice for them.
    mockSignInAsync.mockResolvedValue({ identityToken: 'token' });

    await apple().createAppleProvider().signIn();

    expect(mockSignInAsync).toHaveBeenCalledWith(
      expect.objectContaining({ requestedScopes: [0, 1] })
    );
  });
});
