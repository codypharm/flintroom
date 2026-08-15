import { CancelledByUser, signInWith, type IdentityProvider } from './provider';

/**
 * The seam the platform sign-in SDKs plug into.
 *
 * They are not here yet: Sign in with Apple needs a Developer account with the
 * capability enabled, and Google needs OAuth client IDs minted per platform.
 * Neither can be exercised without those, so what is built now is the shape
 * they satisfy — which `CLAUDE.md` requires anyway, since the Teams tier's SSO
 * constraint means an OIDC provider must slot in without restructuring.
 */
function provider(id: string, result: Promise<string>): IdentityProvider {
  return { id, signIn: () => result };
}

describe('signing in through a provider', () => {
  it('exchanges the provider token under the provider name', async () => {
    const exchanged: { provider: string; idToken: string }[] = [];
    const session = {
      signIn: async (name: string, idToken: string) => {
        exchanged.push({ provider: name, idToken });
      },
    };

    await signInWith(provider('apple', Promise.resolve('apple-id-token')), session);

    expect(exchanged).toEqual([{ provider: 'apple', idToken: 'apple-id-token' }]);
  });

  it('does not exchange anything when the user backs out', async () => {
    // Dismissing the Apple sheet is the single most common outcome of tapping
    // a sign-in button, and it is not an error. Reported as one it becomes an
    // alert saying something went wrong, immediately after the user
    // deliberately made nothing happen.
    const exchanged: string[] = [];
    const session = {
      signIn: async (name: string) => {
        exchanged.push(name);
      },
    };

    const cancelling = provider('apple', Promise.reject(new CancelledByUser()));

    await expect(signInWith(cancelling, session)).rejects.toBeInstanceOf(CancelledByUser);
    expect(exchanged).toEqual([]);
  });
});
