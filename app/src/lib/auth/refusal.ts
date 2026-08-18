import { SignedOut } from './session';

/**
 * What to say when signing in does not work.
 *
 * Three failures reach this, and they want three different things from the
 * person reading:
 *
 *   - the request never left the device — theirs to fix, and worth saying so;
 *   - our server refused the provider's token — nothing they can fix, but
 *     retrying is genuinely worth a go, and it is not a network problem;
 *   - anything else — a server that answered badly, or an SDK that returned
 *     no token at all.
 *
 * What it replaced said "That did not go through. Try again in a moment" to all
 * three. Two things were wrong with that beyond vagueness. It sent somebody
 * with a rejected account to go and check their signal. And "in a moment" is a
 * promise about a resolution nothing here can see: a server returning 500 for
 * an hour is not a moment, and a phone in a tunnel will never become one.
 *
 * **Nothing internal appears in any of these.** The underlying messages carry
 * a request path and a status code, which belong in a log line rather than on
 * a screen a stranger is looking at.
 */
export function refusalFor(error: unknown): string {
  // The string, not `statusCodes.PLAY_SERVICES_NOT_AVAILABLE`, so this file
  // stays free of the native module and testable without one. `google.ts`
  // calls `hasPlayServices()` to make this a typed failure instead of one that
  // dies inside the sheet; the point of doing that is lost if what reaches the
  // screen is the same sentence everything else gets. It is also the only
  // failure here that the person reading can actually go and fix.
  if ((error as { code?: string })?.code === 'PLAY_SERVICES_NOT_AVAILABLE') {
    return 'Google Play services needs an update before you can sign in. Update it, then try again.';
  }

  // React Native rejects `fetch` with a TypeError when the request never
  // reached a server. It is the only cause this code can genuinely identify,
  // and the only one whose recovery belongs to the person reading it.
  if (error instanceof TypeError) {
    return 'We could not reach Flintroom. Check your connection and try again.';
  }

  // A 401 from our own server, which is what `authApi` raises when the
  // provider's token is not accepted. Not the network, and not their fault.
  if (error instanceof SignedOut) {
    return 'We could not verify that account. Try signing in again.';
  }

  return 'Something went wrong on our end. Try signing in again.';
}
