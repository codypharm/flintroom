/**
 * The one place this app reaches into `react-native-audio-api`'s private shape.
 *
 * **Why at all** (#68). The published playback route is `decodeAudioData(url)`,
 * which decodes an entire file into a Float32 buffer before it makes a sound.
 * A room has no length cap — the allowance is monthly minutes, not minutes per
 * room — and a thirty-minute one at 16 kHz mono is about 115 MB of buffer. That
 * is a crash on tapping play, not a refusal, and it lands on the longest and
 * most valuable rooms first.
 *
 * The library's own answer is the `<Audio>` element with
 * `MediaElementAudioSourceNode`, which streams over HTTP ranges and which the
 * README recommends over the now-deprecated `StreamerNode`. It is simply not
 * re-exported from the package root: `lib/typescript/index.d.ts` publishes
 * `./api` and `./hooks` and stops there.
 *
 * **What was weighed.** Adding `expo-audio` alongside would have been a public
 * API and a second audio stack in an app whose open #25 exists to consolidate
 * the one it already has. Deferring into #25 was the standing recommendation
 * and the architect chose to build now instead.
 *
 * **What that costs, stated plainly.** A private path can move under a version
 * bump and no test in this repo would catch it — the failure is at runtime, on
 * a device, when somebody taps play. Two things pay it down and neither is a
 * test:
 *
 *   1. `package.json` pins `react-native-audio-api` to an exact `0.13.2`. A
 *      caret here is what turns "a path we chose" into "a path that changed
 *      while nobody was looking".
 *   2. This file. One importer, one grep, one edit when #25 replaces the layer.
 *      Nothing else in `src/` may name this path.
 *
 * **`lib/module` rather than `src`.** Deep-importing the library's TypeScript
 * source drags its implementation into our own `tsc` run, where it does not
 * compile under `strict` and where `skipLibCheck` does not reach. `lib/module`
 * is the shipped ES build; `src/types/react-native-audio-api-element.d.ts`
 * pairs it with the declarations that ship beside it.
 */

export { default as AudioElement, useAudioTagContext } from 'react-native-audio-api/lib/module/Audio';

export type {
  AudioProps,
  AudioTagHandle,
  AudioTagPlaybackState,
} from 'react-native-audio-api/lib/module/Audio';
