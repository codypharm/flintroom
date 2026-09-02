import { AudioContext, AudioManager, AudioRecorder } from 'react-native-audio-api';

import {
  openNativeCapture,
  openNativePlayback,
  roomAudioAvailable,
} from '../../../modules/room-audio';
import type { PlaybackContext } from './playback';
import type { UplinkRecorder } from './uplink';

/**
 * Which audio stack a screen gets, decided in exactly one place (#25).
 *
 * Two implementations exist while the owned module earns its way in: the
 * library the app shipped on, and `modules/room-audio`. Every screen that
 * opens a microphone or a speaker asks here rather than constructing either
 * directly, so the cutover — and, if hardware disagrees, the retreat — is
 * one constant, not a hunt through call sites.
 *
 * **Owned is dev-only until the pair is proven on a device.** The property
 * that matters is acoustic; `docs/echo-cancellation.md`'s reopen condition
 * says the silent room must be re-measured whenever the audio layer changes,
 * and that measurement needs a phone, not a test suite. Gating on `__DEV__`
 * means a dev-client build exercises the owned pair while every tester build
 * keeps the stack whose numbers are in the doc. Flip `OWNED_IN_RELEASE` when
 * #25's measurement lands, and delete the library the release after.
 */
const OWNED_IN_RELEASE = false;

function preferOwned(): boolean {
  return roomAudioAvailable() && (__DEV__ || OWNED_IN_RELEASE);
}

/** What a screen needs from a microphone, whoever provides it. */
export interface CaptureStack {
  recorder: UplinkRecorder & { start(): unknown; stop(): void };
  /** True when `modules/room-audio` is underneath. Logged, never branched on. */
  owned: boolean;
}

/** What a screen needs from a speaker, whoever provides it. */
export interface PlaybackStack {
  context: PlaybackContext;
  owned: boolean;
  /**
   * Make the output path actually able to make sound.
   *
   * The library's context starts suspended and renders silence *without
   * complaining* if never resumed — the trap both screens document. The
   * owned path opens its stream on `source.start` and needs nothing here.
   * Either way, callers call this once and stop knowing which stack it is.
   */
  ready(): Promise<void>;
  close(): Promise<void>;
}

export function openCaptureStack(): CaptureStack {
  if (preferOwned()) {
    const capture = openNativeCapture();
    if (capture) {
      return { recorder: capture, owned: true };
    }
  }
  return { recorder: new AudioRecorder(), owned: false };
}

export function openPlaybackStack(): PlaybackStack {
  if (preferOwned()) {
    const context = openNativePlayback();
    if (context) {
      return {
        context,
        owned: true,
        ready: async () => {},
        close: async () => context.close(),
      };
    }
  }

  const context = new AudioContext();
  return {
    context,
    owned: false,
    ready: async () => {
      // iOS session options belong to whichever stack is live. The owned
      // module sets its own session natively; the library needs to be told.
      AudioManager.setAudioSessionOptions({
        iosCategory: 'playAndRecord',
        iosMode: 'voiceChat',
        iosOptions: ['defaultToSpeaker', 'allowBluetoothHFP'],
      });
      if (context.state !== 'running') {
        await context.resume();
      }
    },
    close: async () => {
      await context.close().catch(() => undefined);
    },
  };
}
