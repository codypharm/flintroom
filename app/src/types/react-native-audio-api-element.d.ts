/**
 * Types for the one path this app deep-imports.
 *
 * `react-native-audio-api` exports `./api` and `./hooks` from its root and
 * nothing else, so the `<Audio>` element — the only playback route that streams
 * over HTTP ranges instead of decoding a whole room into memory first — is
 * reachable only by a path the package does not publish. #68 records the
 * decision to take that on and pin the version exactly rather than add a second
 * audio stack beside the one #25 exists to consolidate.
 *
 * **Why the built output rather than `src/`.** Deep-importing the library's
 * TypeScript source drags its implementation into our own `tsc` run, where it
 * does not compile: `strict` finds nine errors in files nobody here wrote,
 * `skipLibCheck` does not cover source, and the alternative to this file would
 * have been relaxing our settings for somebody else's code. `lib/module` is the
 * shipped ES build Metro resolves; `lib/typescript` is the declarations that
 * come with it. This only tells the compiler that the two belong together.
 *
 * It is a *declaration*, not a suppression: nothing is silenced, and if the
 * shape changes under a version bump the error lands here rather than nowhere.
 * `src/lib/replay/element.ts` is the only importer.
 */
declare module 'react-native-audio-api/lib/module/Audio' {
  export { default } from 'react-native-audio-api/lib/typescript/Audio';
  export * from 'react-native-audio-api/lib/typescript/Audio';
}
