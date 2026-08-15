/**
 * Where the API lives, as seen from a phone.
 *
 * `localhost` on a device means the device, so a development build has to know
 * the laptop's LAN address — and that address changes every time the laptop
 * joins a different network. Rather than asking for it, we use the one the
 * phone has already proved it can reach: it loaded JavaScript from Metro over
 * that LAN, and Expo hands us the host it used.
 *
 * The arguments are passed in rather than read here, so the rule is testable
 * without a bundler, an environment, or a device.
 */

/** Where the backend listens in development. `backend/` runs uvicorn here. */
const DEV_API_PORT = 8000;

export interface BaseUrlSources {
  /** `EXPO_PUBLIC_API_URL`, if it was set at build time. */
  env: string | undefined;
  /** Metro's host and port, e.g. `192.168.0.5:8081`. Absent outside dev. */
  hostUri: string | undefined;
  /** React Native's `__DEV__`. */
  dev: boolean;
}

export function resolveBaseUrl({ env, hostUri, dev }: BaseUrlSources): string {
  // First, and in every environment. A development build that could not be
  // pointed at staging would mean editing code to change server.
  if (env) {
    return env;
  }

  if (dev && hostUri) {
    // Only the host is taken; Metro's port is not the API's. `hostUri` carries
    // no scheme, so it cannot be parsed as a URL without one.
    const [host] = hostUri.split(':');

    return `http://${host}:${DEV_API_PORT}`;
  }

  // Deliberately fatal, and deliberately at startup. The alternative is a
  // plausible-looking default that fails later as a connection timeout with no
  // diagnostic — on a user's phone, in a release build, where nobody can see
  // which address it tried.
  throw new Error(
    'EXPO_PUBLIC_API_URL is not set, and there is no Metro host to infer one from'
  );
}
