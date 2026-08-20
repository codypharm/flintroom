import type { MicrophoneOutcome } from '../audio/permission';
import type { RoomOrder } from '../room/intent';
import type { DisclosureRecord } from './disclosure';

/**
 * What happens on the tap that opens a room, in the order it has to happen.
 *
 * Four rules, each documented somewhere else, and the ordering between them
 * documented nowhere until here:
 *
 * - **Nothing happens at all until somebody has asked for a room.** #76: this
 *   sequence ends in a metered session, and `/interrogation` used to run it on
 *   mount with nothing but an empty dependency array in the way — so a link on
 *   the `flintroom` scheme, or a remount after `Stack.Protected` re-evaluated
 *   its guard, opened a billed room nobody tapped for. First rather than last,
 *   because the sheet and the system permission prompt are also things that
 *   should not happen to somebody who asked for nothing.
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
  /**
   * What one tap on Start asked for, or null if this was reached another way.
   *
   * A function rather than a value: `takeIntent` spends the order, and doing
   * that at the call site would spend it even on a path that never entered.
   */
  order: () => RoomOrder | null;

  /** The account's window, fetched only when the sheet is going to show it. */
  retentionDays: () => Promise<number>;
  /** Presents the sheet. Resolves when the person continues. */
  disclose: (retentionDays: number) => Promise<void>;
  ensureMicrophone: () => Promise<MicrophoneOutcome>;
  /** Creates the session and its ticket, seated as the order asked. */
  mint: (order: RoomOrder) => Promise<void>;
}

/**
 * `'entered'`, or why the room did not open.
 *
 * `'unasked'` is not a refusal and should not be reported as one. It means
 * nobody tapped anything — the caller has discovered it was reached some way
 * other than by a person asking for a room, and the answer to that is the
 * screen where rooms are started, not an error.
 */
export type RoomEntryOutcome = 'entered' | 'unasked' | MicrophoneOutcome;

export async function enterRoom(entry: RoomEntry): Promise<RoomEntryOutcome> {
  const order = entry.order();
  if (order === null) {
    return 'unasked';
  }

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

  await entry.mint(order);
  return 'entered';
}
