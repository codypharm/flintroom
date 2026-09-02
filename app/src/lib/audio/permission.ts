/**
 * The microphone, settled before a room exists.
 *
 * `docs/onboarding.md` fixes when this runs: at first session start, never at
 * launch, because an iOS denial is sticky and a voice-only app that has been
 * refused the microphone is a dead install. This module owns what happens
 * *after* the answer, which the platform API cannot express on its own.
 */

/** What the caller does next. Three outcomes, because there are three screens. */
export type MicrophoneOutcome =
  /** Mint the session and enter the room. */
  | 'granted'
  /** Explain why the room needs a microphone, and offer to open Settings. */
  | 'denied'
  /** We could not ask. Our failure, not the user's — do not send them to Settings. */
  | 'unavailable';

/**
 * The slice of `expo-audio`'s permission API this needs. Structural, so
 * tests need no native — and shaped after its `PermissionResponse`, which
 * replaced the old library's bare status strings when #25 deleted it.
 */
export interface RecordingPermissions {
  getRecordingPermissionsAsync(): Promise<{ status: string; granted: boolean }>;
  requestRecordingPermissionsAsync(): Promise<{ status: string; granted: boolean }>;
}

export async function ensureMicrophone(
  manager: RecordingPermissions
): Promise<MicrophoneOutcome> {
  try {
    return await settle(manager);
  } catch {
    // Our failure, not the user's, and told apart from theirs deliberately.
    // Reported as denied it would send them to a Settings page to fix a
    // permission they never refused — where they would find it already
    // granted. It must also not throw: this runs on the tap that enters the
    // room, and an unhandled rejection there loses the tap.
    return 'unavailable';
  }
}

async function settle(manager: RecordingPermissions): Promise<MicrophoneOutcome> {
  const existing = await manager.getRecordingPermissionsAsync();

  if (existing.granted) {
    return 'granted';
  }

  // Asked once, ever. The platform reports a denial without saying whether
  // asking again would show anything, and on iOS it never will — the call
  // resolves denied immediately, with no dialog. A retry button that
  // silently does nothing reads as a broken app rather than as a setting
  // the user controls, so a refusal is routed to Settings instead.
  if (existing.status === 'denied') {
    return 'denied';
  }

  return (await manager.requestRecordingPermissionsAsync()).granted ? 'granted' : 'denied';
}
