import {
  GoogleSignin,
  statusCodes,
} from '@react-native-google-signin/google-signin';

import { CancelledByUser, type IdentityProvider } from './provider';

/**
 * Google, as one of our identity providers.
 *
 * Native rather than a browser round trip, which is what the extra dependency
 * buys: a sheet on top of the app instead of a hand-off to Safari or Chrome and
 * back. It needs a dev client, which this project already builds — `patches/`
 * and the `postinstall` hook mean custom native is the normal case here.
 *
 * **`webClientId` is the one that has to be right.** Google addresses an ID
 * token to whichever client asked for it, and this SDK asks with the *web*
 * client — its own docs call `webClientId` "the client ID of type WEB for your
 * server". That is the value `OidcVerifier` pins as `aud`. Passing the iOS one
 * here mints tokens the backend refuses, as a 401 that names nothing, because
 * `sign_in` deliberately never says which check failed. That mistake cost a day
 * on the server side of this feature; it does not get to happen twice.
 *
 * `iosClientId` is separate and does a different job — it is how the SDK finds
 * the URL scheme to come back through on iOS. Both are needed, for two reasons.
 */

/**
 * Read statically, at module scope, and both parts of that matter.
 *
 * **Statically**, because Expo inlines `EXPO_PUBLIC_*` by *textual* substitution
 * of dot notation into the bundle — `process.env[name]` is never replaced and is
 * simply `undefined` on a device. This file originally passed the variable name
 * to a helper and read `process.env[name]`, which typechecked, passed its tests
 * against Node's real `process.env`, and then failed on the first simulator
 * launch with "not set" for a variable that was set. `room.tsx` already carried
 * the same warning; this is the second time the project has paid for it.
 *
 * **At module scope**, so a release built without the variable fails when the
 * screen loads rather than shipping a working-looking button that fails on every
 * tap in the field — the same argument `lib/auth/index.ts` makes for resolving
 * the API base URL eagerly.
 */
const WEB_CLIENT_ID = process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID;
const IOS_CLIENT_ID = process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID;

function required(value: string | undefined, name: string): string {
  if (!value) {
    throw new Error(`${name} is not set. Google sign-in cannot be configured.`);
  }

  return value;
}

export function createGoogleProvider(): IdentityProvider {
  GoogleSignin.configure({
    webClientId: required(WEB_CLIENT_ID, 'EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID'),
    iosClientId: required(IOS_CLIENT_ID, 'EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID'),
  });

  return {
    id: 'google',

    async signIn(): Promise<string> {
      try {
        // Android only, and a no-op elsewhere. Without it a device whose Play
        // Services are missing or stale fails inside the sheet with a message
        // the user can do nothing about.
        await GoogleSignin.hasPlayServices();

        const { data } = await GoogleSignin.signIn();

        if (!data?.idToken) {
          // The SDK resolves with no data when the flow completes without a
          // credential. Passing that on posts an empty token and gets refused a
          // round trip later, somewhere with no idea why.
          throw new Error('Google returned no token.');
        }

        return data.idToken;
      } catch (error) {
        if ((error as { code?: string })?.code === statusCodes.SIGN_IN_CANCELLED) {
          throw new CancelledByUser();
        }

        throw error;
      }
    },
  };
}
