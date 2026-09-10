import type * as ExpoNetwork from 'expo-network';

import { isOffline, type NetworkProbe } from './offline';

/**
 * The real API satisfies the structural interface, checked by the typechecker
 * rather than assumed — the same check that caught an invented option name in
 * `uplink.ts`. A *type-only* import, because an Expo native module cannot be
 * evaluated under Jest, which is also why `isOffline` takes the API as a
 * parameter instead of importing it.
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function theRealNetworkFits(
  api: Pick<typeof ExpoNetwork, 'getNetworkStateAsync'>
): NetworkProbe {
  return api;
}

/**
 * Whether to blame the network, asked only when something has already failed.
 *
 * There is no listener and no banner. A connectivity subscription would be a
 * claim the app makes continuously and can be wrong about continuously —
 * captive portals report a healthy connection, and a banner that says "offline"
 * to somebody whose browser works reads as the app being broken. Asked at the
 * moment of a failure, the answer is only ever used to explain something the
 * user has already seen go wrong.
 *
 * The bias runs one way: claim offline only when the platform says so. Being
 * wrong in that direction sends somebody to check a connection that was fine;
 * being wrong in the other only leaves the message we already had.
 */

function probe(state: {
  isConnected?: boolean | null;
  isInternetReachable?: boolean | null;
}): NetworkProbe {
  return { getNetworkStateAsync: () => Promise.resolve(state) };
}

it('is offline when the platform says nothing is connected', async () => {
  await expect(isOffline(probe({ isConnected: false }))).resolves.toBe(true);
});

it('is offline on a network that cannot reach the internet', async () => {
  // Hotel wifi and captive portals: associated, full signal bars, and no route
  // out. This is the case the whole feature exists for, because it is the one
  // where the user is most certain the fault is ours.
  await expect(
    isOffline(probe({ isConnected: true, isInternetReachable: false }))
  ).resolves.toBe(true);
});

it('is not offline when the connection is working', async () => {
  await expect(
    isOffline(probe({ isConnected: true, isInternetReachable: true }))
  ).resolves.toBe(false);
});

it('does not claim offline when the platform will not say', async () => {
  // `isInternetReachable` is not answered on every platform and every version.
  // Unknown is not the same as down, and guessing here would tell somebody to
  // fix a connection that was never broken.
  await expect(
    isOffline(probe({ isConnected: true, isInternetReachable: undefined }))
  ).resolves.toBe(false);
  await expect(isOffline(probe({}))).resolves.toBe(false);
});

it('never blames the network when the check itself fails', async () => {
  // A native call that throws is our failure. It also must not throw onwards:
  // this runs inside an error path, and an unhandled rejection there would
  // replace a refusal somebody could act on with a crash.
  const broken: NetworkProbe = {
    getNetworkStateAsync: () => Promise.reject(new Error('native module missing')),
  };

  await expect(isOffline(broken)).resolves.toBe(false);
});
