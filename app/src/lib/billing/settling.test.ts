import { answersWithin, settles, SETTLE_ATTEMPTS, SETTLE_GAP_MS } from './settling';

/**
 * Waiting for a purchase to become minutes.
 *
 * A purchase is three moments and only the first is on the device: the store is
 * satisfied, RevenueCat calls our webhook, `grant_topup` moves the balance. The
 * middle one is a network hop between two companies and can be slow.
 *
 * So the screen cannot show new minutes when `buy()` resolves — it would be
 * stating a number the server has not agreed to. It waits, and this is the
 * waiting. In `lib/` rather than in the route because routes carry no tests by
 * convention (`CLAUDE.md` → Frontend) and this is the part with behaviour.
 */

/** A reader that returns each figure in turn, then repeats the last forever. */
function reads(...figures: number[]) {
  let at = 0;
  return async () => figures[Math.min(at++, figures.length - 1)];
}

it('stops the moment the balance moves', async () => {
  const pause = jest.fn().mockResolvedValue(undefined);

  expect(await settles(reads(12, 12, 32), 12, { pause })).toBe(true);

  // Three, not ten. It stops on the read that moved rather than exhausting the
  // budget — one pause per read, because it always waits before asking, and no
  // pause at all after the answer arrives.
  expect(pause).toHaveBeenCalledTimes(3);
});

it('gives up rather than waiting forever', async () => {
  // A webhook that never lands is a real outcome — a store outage, a
  // misconfigured secret, a purchase that genuinely failed after the sheet
  // closed. The screen has to be able to stop and say something honest instead
  // of spinning until the app is killed.
  const pause = jest.fn().mockResolvedValue(undefined);

  expect(await settles(reads(12), 12, { pause })).toBe(false);
  expect(pause).toHaveBeenCalledTimes(SETTLE_ATTEMPTS);
});

it('treats a balance that went down as unsettled, never as movement', async () => {
  // A tick from a room running on another device can land mid-wait. Any change
  // would read that as the purchase arriving and stop early, showing a smaller
  // number as though it were the new one.
  const pause = jest.fn().mockResolvedValue(undefined);

  expect(await settles(reads(11), 12, { pause })).toBe(false);
});

it('survives a read that fails without abandoning the wait', async () => {
  // The balance endpoint failing once during the wait is ordinary — the phone
  // moved between networks. Giving up on it would report a purchase as lost
  // because of an unrelated blip.
  const pause = jest.fn().mockResolvedValue(undefined);
  let at = 0;
  const read = async () => {
    at += 1;
    if (at === 1) throw new Error('offline');
    return 32;
  };

  expect(await settles(read, 12, { pause })).toBe(true);
});

it('never reads before waiting once', async () => {
  // The caller has just been told the store is satisfied. Reading immediately
  // asks the server a question it cannot yet have the answer to, and burns an
  // attempt on a certainty.
  const order: string[] = [];
  const pause = jest.fn().mockImplementation(async () => {
    order.push('pause');
  });
  const read = async () => {
    order.push('read');
    return 32;
  };

  await settles(read, 12, { pause });

  expect(order[0]).toBe('pause');
});

describe('a store that goes quiet', () => {
  // 2026-10-02, an iOS sandbox top-up: `purchasePackage` never resolved, the
  // screen sat dimmed with every control disabled, and the minutes only
  // arrived after the app was killed and reopened. Apple's own "successful"
  // sheet came later still. The screen trusted the store to answer and had no
  // way out when it did not.

  /** A pause that never ends, standing in for a store still thinking. */
  const forever = () => new Promise<void>(() => undefined);

  it('reports an answer that came in time', async () => {
    expect(await answersWithin(Promise.resolve(), 20_000, forever)).toBe(true);
  });

  it('reports silence once the patience runs out', async () => {
    const pending = new Promise<void>(() => undefined);
    const pause = jest.fn().mockResolvedValue(undefined);

    expect(await answersWithin(pending, 20_000, pause)).toBe(false);
    expect(pause).toHaveBeenCalledWith(20_000);
  });

  it('passes on a refusal that came in time', async () => {
    // A closed sheet or a declined card still has to reach the screen as
    // itself, or a cancel would read as a purchase being confirmed.
    const refused = Promise.reject(new Error('declined'));

    await expect(answersWithin(refused, 20_000, forever)).rejects.toThrow('declined');
  });

  it('swallows a refusal that came after it stopped listening', async () => {
    // By then the screen is waiting on the server, not the store. An
    // unhandled rejection here would surface as a red box over a purchase
    // that may well have gone through.
    let refuse: (why: Error) => void = () => undefined;
    const late = new Promise<void>((_, no) => {
      refuse = no;
    });
    const pause = jest.fn().mockResolvedValue(undefined);

    expect(await answersWithin(late, 20_000, pause)).toBe(false);
    refuse(new Error('too late'));
    await new Promise((done) => setImmediate(done));
  });
});

it('keeps asking for at least two minutes', () => {
  // Measured, 2026-10-04: an iOS sandbox top-up reached the webhook about 80
  // seconds after it was bought, one second after the old 30-second window
  // closed. The minutes arrived and the screen had already stopped looking.
  expect(SETTLE_ATTEMPTS * SETTLE_GAP_MS).toBeGreaterThanOrEqual(120_000);
});
