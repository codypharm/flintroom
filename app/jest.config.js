/**
 * One runner for everything the client tests.
 *
 * `jest-expo` is the preset because component tests need React Native's module
 * resolution and its transform of the untranspiled ESM that ships inside
 * `node_modules/react-native` and friends. Pure logic — PCM conversion, the
 * connect sequence, close-code routing — needs none of that, but it runs here
 * too: a second runner would be a second config, a second mocking story, and a
 * rule about which one a new file belongs to. See `CLAUDE.md` → Frontend.
 *
 * The preset is pinned to `jest-expo/ios` rather than the multi-platform one.
 * The default preset runs every test once per platform, which for logic with no
 * platform branches is the same assertion three times at three times the cost.
 * Where behaviour genuinely diverges by platform — the audio session, which is
 * the one place we already know it does — the divergence is behind a module
 * boundary and gets its own test, not a matrix over the whole suite.
 */
module.exports = {
  preset: 'jest-expo/ios',
  // No setup file. `@testing-library/react-native` v14 registers its matchers
  // on import, so there is nothing to extend, and an empty setup file is an
  // invitation to fill it with global mocks — which is how a test ends up
  // passing against a fake nobody in that file chose.
  testPathIgnorePatterns: ['/node_modules/', '/.expo/'],
  collectCoverageFrom: ['src/**/*.{ts,tsx}', '!src/lib/api/schema.d.ts'],
};
