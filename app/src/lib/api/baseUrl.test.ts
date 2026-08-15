import { resolveBaseUrl } from './baseUrl';

/**
 * Where the API lives, as seen from a phone.
 *
 * `localhost` on a device means the device, so a development build has to be
 * told the laptop's LAN address — and that address changes with the network.
 * Rather than ask for it, the phone has already found it: it reached Metro
 * over the same LAN, and Expo hands us that host.
 *
 * A wrong answer here fails as a connection timeout with no diagnostic, which
 * is why the production path refuses to guess at all.
 */
describe('resolving the API base URL', () => {
  it('prefers the environment variable, wherever it is set', () => {
    // The only mechanism that exists in a real build, and it must also win in
    // development — otherwise pointing the app at staging would mean editing
    // code.
    expect(
      resolveBaseUrl({
        env: 'https://api.flintroom.app',
        hostUri: '192.168.0.5:8081',
        dev: true,
      })
    ).toBe('https://api.flintroom.app');
  });

  it('follows the host the phone already reached Metro on', () => {
    // The address is not guessed: the device demonstrably reached this host,
    // because that is where its JavaScript came from. Metro's port is not the
    // API's, so only the host is taken.
    expect(resolveBaseUrl({ env: undefined, hostUri: '192.168.0.5:8081', dev: true })).toBe(
      'http://192.168.0.5:8000'
    );
  });

  it('refuses to invent one for a real build', () => {
    // Failing loudly at startup, rather than defaulting to something plausible
    // that fails later as a connection timeout with no diagnostic — on a
    // user's phone, where nobody can see which address it tried.
    expect(() => resolveBaseUrl({ env: undefined, hostUri: undefined, dev: false })).toThrow(
      /EXPO_PUBLIC_API_URL/
    );
  });

  it('does not infer a host outside development', () => {
    // A production build that somehow carries a Metro host must still refuse.
    // Inferring there would point a shipped app at a LAN address belonging to
    // whoever built it.
    expect(() => resolveBaseUrl({ env: undefined, hostUri: '192.168.0.5:8081', dev: false })).toThrow();
  });
});
