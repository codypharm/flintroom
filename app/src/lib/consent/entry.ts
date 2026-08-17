import type { MicrophoneOutcome } from '../audio/permission';
import type { DisclosureRecord } from './disclosure';

/**
 * What happens on the tap that opens a room, in the order it has to happen.
 *
 * Three rules, each documented somewhere else, and the ordering between them
 * documented nowhere until here:
 *
 * - The disclosure comes **before** the system microphone prompt.
 *   `docs/onboarding.md` puts the ask at the moment its reason is
 *   self-evident, and the sheet is that reason. Afterwards it would be an
 *   explanation for something already granted.
 * - The microphone is settled **before** the session is minted. A stream ticket
 *   expires in seconds, so minting first leaves somebody who tapped "don't
 *   allow" holding a dead ticket against a live session that has to be reaped
 *   rather than never created.
 * - The disclosure is remembered **whatever happens next**. They were told; a
 *   sheet that reappeared after a refused microphone would imply otherwise.
 *
 * Kept out of the screen because a screen is where ordering goes to be
 * accidentally rearranged — this is the sequence, and it is testable without a
 * renderer, a keychain or a permission dialog.
 */

export interface RoomEntry {
  userId: string;
  record: DisclosureRecord;
  /** The account's window, fetched only when the sheet is going to show it. */
  retentionDays: () => Promise<number>;
  /** Presents the sheet. Resolves when the person continues. */
  disclose: (retentionDays: number) => Promise<void>;
  ensureMicrophone: () => Promise<MicrophoneOutcome>;
  /** Creates the session and its ticket. */
  mint: () => Promise<void>;
}

/** `'entered'`, or why the room did not open. */
export type RoomEntryOutcome = 'entered' | MicrophoneOutcome;

export async function enterRoom(entry: RoomEntry): Promise<RoomEntryOutcome> {
  if (!(await entry.record.wasShownTo(entry.userId))) {
    // Fetched inside the branch, not above it. A returning user taps this to
    // start every rehearsal they ever do, and a request on that path for a
    // number nothing will render is latency spent on nothing.
    await entry.disclose(await entry.retentionDays());
    await entry.record.rememberShownTo(entry.userId);
  }

  const microphone = await entry.ensureMicrophone();

  if (microphone !== 'granted') {
    return microphone;
  }

  await entry.mint();
  return 'entered';
}
