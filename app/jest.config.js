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
 * **`render()` must be awaited.** `await render(<Thing />)`, never bare. React
 * 19's concurrent root means the tree is not committed when `render` returns,
 * so `screen` is still unset — and the error it raises then is
 * *"`render` function has not been called"*, which sends you looking at the
 * wrong thing entirely. It is a lie: it was called, and it had not finished.
 * Every component test here awaits; a new one that does not will fail with that
 * message against a component that is perfectly fine.
 *
 * **An act() scope left open poisons the *next* test.** Same family, different
 * symptom. A bare `fireEvent` for a synthetic event — `layout` is the one that
 * caught this — issued outside `await act(async () => ...)` can leave React 19's
 * act scope open across the end of the test body, and React then discards the
 * following test's tree. What you see is "unable to find an element" against a
 * component that is perfectly fine, in a test three names further down, while
 * the same test passes alone. The tell is `console.error: You seem to have
 * overlapping act() calls` above the failures, and `screen.debug()` printing an
 * empty tree. Wrap and await.
 *
 * **One `render` per test.** Two roots in one body leaves `screen` pointing at a
 * tree cleanup has already detached, with the same misleading failure.
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
