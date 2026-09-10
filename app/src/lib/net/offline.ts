/**
 * Whether the phone itself is the reason something just failed.
 *
 * Flintroom is online by construction: a room is a socket, and a coaching turn
 * is an HTTP request. There is no offline mode to build and none is implied
 * here. What this answers is narrower and only ever asked after a failure —
 * *whose* connection to name in the sentence the user reads.
 *
 * Before this existed, dead hotel wifi and a backend outage produced the same
 * words. The two have opposite recoveries: one is "move nearer the router",
 * the other is "wait for us". A refusal that cannot tell them apart sends
 * everybody to the same wrong place, and the natural reading of a generic
 * failure in a voice product is that the app is broken.
 *
 * **No listener, no banner.** A connectivity subscription is a claim the app
 * makes continuously and can be wrong about continuously — a captive portal
 * reports a healthy network, and a banner reading "offline" beside a working
 * browser destroys more trust than the message it replaces. Asked at the
 * moment of a failure, the answer only ever explains something already seen to
 * go wrong.
 *
 * **The API is a parameter, not an import.** Same reason as
 * `lib/audio/permission.ts`: an Expo native module cannot be evaluated under
 * Jest, and a module that reaches for one directly drags a mock into every
 * test that transitively touches it.
 */

export interface NetworkProbe {
  getNetworkStateAsync(): Promise<{
    isConnected?: boolean | null;
    isInternetReachable?: boolean | null;
  }>;
}

/**
 * True only when the platform says the connection is down.
 *
 * Deliberately one-sided. Unknown is not down: `isInternetReachable` goes
 * unanswered on some platforms and versions, and treating silence as a verdict
 * would send people to fix a connection that was never broken. Being wrong the
 * other way costs nothing beyond keeping the message we already had.
 *
 * Never throws. This runs inside an error path, where an unhandled rejection
 * would replace a refusal somebody could act on with a crash.
 */
export async function isOffline(probe: NetworkProbe): Promise<boolean> {
  try {
    const state = await probe.getNetworkStateAsync();

    if (state.isConnected === false) {
      return true;
    }

    // Associated with a network that has no route out: hotel wifi, a captive
    // portal, a train. The case this exists for, and the one where the user is
    // most certain the fault is ours.
    return state.isInternetReachable === false;
  } catch {
    // Our failure, not their network.
    return false;
  }
}
