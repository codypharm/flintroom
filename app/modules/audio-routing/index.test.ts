/**
 * Which speaker the panel comes out of.
 *
 * Android routes a `VOICE_COMMUNICATION` stream to the *earpiece* unless the
 * app puts `AudioManager` into communication mode — see
 * `docs/echo-cancellation.md`. Flintroom is a phone lying flat on a desk, so
 * the earpiece points at the ceiling and the room hears almost nothing. This is
 * the module that says otherwise.
 *
 * Presence of the native module is the only platform check. It is declared
 * `platforms: ["android"]`, so asking whether it exists and asking whether we
 * are on Android are the same question — and one mechanism cannot disagree with
 * itself the way a `Platform.OS` test sitting next to it eventually would.
 *
 * Each test loads `./index` fresh after deciding what `./src/native` resolves
 * to, because the module reads it once at import.
 */
function loadWith(nativeModule: unknown) {
  jest.resetModules();
  jest.doMock('./src/native', () => ({ __esModule: true, default: nativeModule }));

  return require('./index') as typeof import('./index');
}

describe('when the native module is absent', () => {
  it('does nothing rather than throwing', async () => {
    // iOS, web, and the Android emulator before a rebuild all land here. A
    // throw would take down the screen over a routing preference, which is the
    // wrong trade: audio still plays, it just plays out of the default device.
    const routing = loadWith(null);

    await expect(routing.enterHandsFree()).resolves.toBe(false);
    expect(() => routing.leaveHandsFree()).not.toThrow();
  });
});

describe('when the native module is present', () => {
  const present = {
    enterHandsFree: jest.fn().mockResolvedValue(true),
    leaveHandsFree: jest.fn(),
  };

  beforeEach(() => {
    present.enterHandsFree.mockClear();
    present.leaveHandsFree.mockClear();
  });

  it('asks for the loudspeaker on the way in', async () => {
    await loadWith(present).enterHandsFree();

    expect(present.enterHandsFree).toHaveBeenCalledTimes(1);
  });

  it('reports whether routing actually settled', async () => {
    // The caller has to be able to tell "the speaker is live" from "we asked
    // and nothing happened", because opening the recorder before routing
    // settles is what gets its stream stolen — the zero-buffer bug.
    present.enterHandsFree.mockResolvedValueOnce(false);

    await expect(loadWith(present).enterHandsFree()).resolves.toBe(false);
  });

  it('hands routing back on the way out', () => {
    // Leaving the phone in communication mode after a session is not cosmetic:
    // the mode is process-wide and outlives the screen, so every later sound
    // the app makes keeps the call-audio routing and the volume rocker keeps
    // adjusting the wrong stream.
    loadWith(present).leaveHandsFree();

    expect(present.leaveHandsFree).toHaveBeenCalledTimes(1);
  });
});
