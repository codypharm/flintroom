import { requireOptionalNativeModule } from 'expo-modules-core';

export interface AudioRoutingNative {
  /** Resolves when routing has moved, `true` if it reached the loudspeaker. */
  enterHandsFree(): Promise<boolean>;
  leaveHandsFree(): void;
}

/**
 * The Android implementation, or `null` everywhere else.
 *
 * `requireOptionalNativeModule` rather than `requireNativeModule`: the module is
 * declared `platforms: ["android"]`, so on iOS and web there is nothing to bind
 * and the strict version throws at *import* time — which would take the whole
 * bundle down, not just this call. Returning null lets the caller decide, and
 * the caller's decision is "carry on quietly".
 */
export default requireOptionalNativeModule<AudioRoutingNative>('AudioRouting');
