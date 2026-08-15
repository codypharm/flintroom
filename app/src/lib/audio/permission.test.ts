import { AudioManager } from 'react-native-audio-api';

import { ensureMicrophone, type RecordingPermissions } from './permission';

/**
 * The real manager satisfies the structural interface, checked by the
 * typechecker rather than assumed. The same check caught an invented option
 * name in `uplink.ts`, where every test passed against a shape that did not
 * exist.
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function theRealManagerFits(manager: typeof AudioManager): RecordingPermissions {
  return manager;
}

/**
 * The microphone, asked for at the moment its reason is obvious.
 *
 * `docs/onboarding.md` fixes the timing: at first session start, never at
 * launch. An iOS denial is sticky — the app cannot re-prompt, and the user has
 * to find a toggle in Settings — so for a voice-only product a badly-timed
 * prompt is a dead install. It is also what App Store reviewers look for
 * (Open Risk #5).
 *
 * What this module adds is the ordering: permission is settled *before* a
 * session exists. A room minted for a user who then refuses the microphone is
 * a room nobody can speak in, holding a ticket and a session row.
 */
class FakeAudioManager {
  requests = 0;
  checks = 0;

  constructor(
    private status: 'Undetermined' | 'Denied' | 'Granted',
    private readonly grantsOnRequest: 'Granted' | 'Denied' = 'Granted'
  ) {}

  async checkRecordingPermissions() {
    this.checks += 1;
    return this.status;
  }

  async requestRecordingPermissions() {
    this.requests += 1;
    this.status = this.grantsOnRequest;
    return this.status;
  }
}

describe('asking for the microphone', () => {
  it('prompts when the user has not been asked before', async () => {
    const manager = new FakeAudioManager('Undetermined');

    await expect(ensureMicrophone(manager)).resolves.toBe('granted');
    expect(manager.requests).toBe(1);
  });

  it('never asks twice once the user has said no', async () => {
    // The platform reports 'Denied' without saying whether asking again would
    // do anything, and on iOS it never would — the call resolves 'Denied'
    // immediately with no dialog shown. Re-requesting therefore produces a
    // button that appears to do nothing, which reads as the app being broken
    // rather than as a setting the user controls. We explain and offer
    // Settings instead.
    const manager = new FakeAudioManager('Denied');

    await expect(ensureMicrophone(manager)).resolves.toBe('denied');
    expect(manager.requests).toBe(0);
  });

  it('does not prompt a user who has already granted it', async () => {
    // Every session start runs through here, not just the first. A prompt on
    // the second session would be the OS dialog appearing for no reason the
    // user can see.
    const manager = new FakeAudioManager('Granted');

    await expect(ensureMicrophone(manager)).resolves.toBe('granted');
    expect(manager.requests).toBe(0);
  });

  it('reports a refusal at the prompt as denied', async () => {
    const manager = new FakeAudioManager('Undetermined', 'Denied');

    await expect(ensureMicrophone(manager)).resolves.toBe('denied');
  });

  it('separates "we could not ask" from "the user said no"', async () => {
    // A native call that throws is our failure, not the user's. Reporting it
    // as denied would send them to a Settings page to fix a permission they
    // never refused — where they would find it already granted, and conclude
    // the app is lying to them. It also has to not throw: this runs on the tap
    // that enters the room, and an unhandled rejection there loses the tap.
    const broken = {
      checkRecordingPermissions: () => Promise.reject(new Error('native module not linked')),
      requestRecordingPermissions: () => Promise.reject(new Error('native module not linked')),
    };

    await expect(ensureMicrophone(broken)).resolves.toBe('unavailable');
  });
});
