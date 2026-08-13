/**
 * Written down for Jest's sake, not Metro's.
 *
 * SDK 57 ships no `babel.config.js` because `@expo/metro-config` applies
 * `babel-preset-expo` internally. Jest transforms through `babel-jest`, which
 * looks for a config file and finds nothing — so React Native's own setup
 * files, which are Flow-annotated JavaScript, reach the parser with their types
 * intact and fail to parse.
 *
 * This restates Metro's existing default rather than changing it. Metro will
 * now read this file instead of its built-in config, so it must stay equivalent
 * to that default: anything added here silently changes how the app is bundled,
 * not just how it is tested.
 */
module.exports = function (api) {
  api.cache(true);

  return {
    presets: ['babel-preset-expo'],
  };
};
