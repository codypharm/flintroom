import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * What the store is promised about this app, guarded at the source of truth.
 *
 * `android/` and `ios/` are generated and gitignored: EAS runs a fresh
 * prebuild from `app.json` on every build, so a manifest edited by hand is a
 * file no build ever sees. That cost two releases on 2026-09-03 — the
 * foreground-service permissions were deleted from the generated manifest,
 * the app was rebuilt twice, and Play kept flagging it, because
 * `expo-audio`'s config plugin re-added them from a default nobody had set.
 *
 * A permission is not only a technical fact. FOREGROUND_SERVICE_MEDIA_PLAYBACK
 * obliges a Play declaration that the app "performs tasks noticeable to the
 * user when they're not directly interacting with it" — which this app does
 * not do: the live room holds the screen awake and everything else plays in
 * the foreground. Declaring it would be claiming a capability we do not ship.
 */

const config = JSON.parse(
  readFileSync(join(__dirname, '../../app.json'), 'utf8')
) as {
  expo: {
    plugins: (string | [string, Record<string, unknown>])[];
    android: { permissions: string[] };
  };
};

function pluginOptions(name: string): Record<string, unknown> | null {
  for (const entry of config.expo.plugins) {
    if (Array.isArray(entry) && entry[0] === name) {
      return entry[1];
    }
    if (entry === name) {
      // Listed bare, so every one of the plugin's defaults applies.
      return {};
    }
  }
  return null;
}

describe('the Android permissions this app ships', () => {
  it('turns off expo-audio background playback, which is what adds them', () => {
    // `enableBackgroundPlayback` defaults to *true*, and true adds
    // FOREGROUND_SERVICE, FOREGROUND_SERVICE_MEDIA_PLAYBACK and a media
    // controls service. Listing the plugin bare is enough to bring all three
    // back, which is why this asserts the option rather than the absence.
    expect(pluginOptions('expo-audio')).toEqual({ enableBackgroundPlayback: false });
  });

  it('asks for no foreground service permission directly either', () => {
    const foreground = config.expo.android.permissions.filter((permission) =>
      permission.includes('FOREGROUND_SERVICE')
    );

    expect(foreground).toEqual([]);
  });

  it('still asks for the microphone, which the room cannot open without', () => {
    // The counterweight: a test that only removes things passes just as well
    // against an app that asks for nothing and cannot hear anybody.
    expect(config.expo.android.permissions).toContain('android.permission.RECORD_AUDIO');
  });
});
