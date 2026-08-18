import * as AppleAuthentication from 'expo-apple-authentication';

import { CancelledByUser, type IdentityProvider } from './provider';

/**
 * Apple, as one of our identity providers.
 *
 * **Not a choice, unlike Google.** Offering a third-party sign-in on iOS makes
 * Sign in with Apple mandatory there (App Store guideline 4.8), and Apple wants
 * the *native* flow — a web round trip through `expo-auth-session` would work
 * technically and fail review. So the package is settled by the store.
 *
 * iOS only, and that is the module rather than a decision of ours: it has no
 * Android implementation at all. `isAvailable` is the gate rather than a
 * `Platform.OS` check, because it answers the same on Android *and* catches an
 * iOS version or a simulator with no Apple ID signed in — cases where a
 * platform check renders a button that throws when tapped.
 *
 * The token our server verifies is `identityToken`, and its `aud` is the app's
 * **bundle identifier** — `com.flintroom.app` — not a Services ID. Services IDs
 * belong to the web flow this product does not have, and `APPLE_CLIENT_ID` on
 * the server has to hold the bundle id or every sign-in fails audience
 * verification with an error that reads like a broken key.
 */

/** Whether this device can sign in with Apple at all. */
export async function isAppleAvailable(): Promise<boolean> {
  try {
    return await AppleAuthentication.isAvailableAsync();
  } catch {
    // Any failure here means unavailable. A thrown probe must not stop the
    // screen rendering the Google button, which is the whole point of asking.
    return false;
  }
}

export function createAppleProvider(): IdentityProvider {
  return {
    id: 'apple',

    async signIn(): Promise<string> {
      try {
        const credential = await AppleAuthentication.signInAsync({
          // Both requested, and both may be null. Apple returns name and email
          // on the *first* authorization only, and never again — but neither is
          // sent anywhere: the server reads the token's claims. They are asked
          // for because the consent sheet is where a user chooses Hide My
          // Email, and not asking would silently make that choice for them.
          requestedScopes: [
            AppleAuthentication.AppleAuthenticationScope.FULL_NAME,
            AppleAuthentication.AppleAuthenticationScope.EMAIL,
          ],
        });

        if (!credential.identityToken) {
          throw new Error('Apple returned no token.');
        }

        return credential.identityToken;
      } catch (error) {
        if ((error as { code?: string })?.code === 'ERR_REQUEST_CANCELED') {
          throw new CancelledByUser();
        }

        throw error;
      }
    },
  };
}
