import Constants from 'expo-constants';
import * as SecureStore from 'expo-secure-store';

import { createAuthApi } from '../api/authApi';
import { resolveBaseUrl } from '../api/baseUrl';
import { createAuthSession } from './session';
import { createTokenStore } from './tokens';

/**
 * The one place the auth pieces are assembled from real things.
 *
 * Everything below this line is injectable and tested against fakes; this file
 * is where the fakes are replaced by the keychain, the network and the
 * environment. Keeping that in a single module is what lets the rest of the
 * client be tested without a device — and it is the only file here that has
 * never been executed by a test, which is why it contains no logic to get
 * wrong.
 */

/**
 * Resolved once, at import.
 *
 * Deliberately eager: a missing `EXPO_PUBLIC_API_URL` in a release build is a
 * misconfiguration that should stop the app immediately, with a message naming
 * the variable — not surface later as a connection timeout on a user's phone,
 * where nothing says which address was tried.
 */
export const API_BASE_URL = resolveBaseUrl({
  env: process.env.EXPO_PUBLIC_API_URL,
  // Metro's host, e.g. `192.168.0.5:8081` — the address this phone has already
  // proved it can reach, since that is where its JavaScript came from.
  hostUri: Constants.expoConfig?.hostUri,
  dev: __DEV__,
});

/**
 * The signed-in session, shared by everything that makes a request.
 *
 * One instance, and it has to be: the single-flight refresh in `session.ts`
 * only prevents a stampede among callers that share it. Two instances would
 * each think they were the only one refreshing, present the same refresh token,
 * and the server would read the second as theft and end the session on every
 * device.
 */
export const auth = createAuthSession({
  api: createAuthApi({ baseUrl: API_BASE_URL }),
  store: createTokenStore(SecureStore),
});
