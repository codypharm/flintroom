/**
 * Where an identity comes from, before it becomes one of our sessions.
 *
 * An interface rather than two functions, for a reason `CLAUDE.md` already
 * fixes: the Teams tier sells seats to organizations, organizations want SSO,
 * and an OIDC provider has to slot in without restructuring what is here. It
 * is free to preserve now and expensive to retrofit — the same argument as the
 * voice provider.
 *
 * The platform SDKs are deliberately absent. Sign in with Apple needs a
 * Developer account with the capability enabled on the App ID; Google needs
 * OAuth client IDs minted per platform. Adding either before those exist would
 * mean shipping code that has never once been run.
 */

/**
 * The user dismissed the sheet.
 *
 * Typed separately because it is the most common outcome of tapping a sign-in
 * button and it is not a failure. Left as a generic error it becomes an alert
 * saying something went wrong, shown immediately after the user deliberately
 * made nothing happen.
 */
export class CancelledByUser extends Error {
  constructor() {
    super('Sign-in was cancelled');
    this.name = 'CancelledByUser';
  }
}

export interface IdentityProvider {
  /**
   * What the server calls this provider — the `provider` field on the wire.
   *
   * A plain string, matching the contract: a closed set would answer an
   * unrecognised value by listing the ones we accept, which enumerates our
   * configuration to anyone who asks.
   */
  readonly id: string;
  /** Runs the native flow and returns the provider's ID token. */
  signIn(): Promise<string>;
}

/** Just enough of `AuthSession` to exchange a token, so this stays testable alone. */
export interface TokenExchange {
  signIn(provider: string, idToken: string): Promise<void>;
}

export async function signInWith(
  provider: IdentityProvider,
  session: TokenExchange
): Promise<void> {
  await session.signIn(provider.id, await provider.signIn());
}
