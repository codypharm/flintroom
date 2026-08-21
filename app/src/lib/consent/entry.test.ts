import { createDisclosureRecord } from './disclosure';
import { enterRoom } from './entry';

/**
 * The order of the three things that happen on the tap that opens a room.
 *
 * Each is documented separately and the ordering between them is the part
 * nothing else states: the disclosure comes before the system microphone prompt
 * (`docs/onboarding.md` puts the ask where its reason is self-evident, and the
 * sheet is that reason), and the session is minted only once the microphone is
 * settled (a ticket expires in seconds, so minting first leaves a dead ticket
 * against a live session that has to be reaped).
 *
 * Reordered, every individual piece still works and the room is quietly worse.
 */

const ADA = 'e6f1c0d2-0000-4000-8000-000000000001';

function storage() {
  const values = new Map<string, string>();
  return {
    getItemAsync: async (key: string) => values.get(key) ?? null,
    setItemAsync: async (key: string, value: string) => void values.set(key, value),
  };
}

function trace() {
  const steps: string[] = [];
  return {
    steps,
    deps: {
      userId: ADA,
      record: createDisclosureRecord(storage()),
      retentionDays: async () => {
        steps.push('window');
        return 30;
      },
      disclose: async () => void steps.push('disclose'),
      ensureMicrophone: async () => {
        steps.push('microphone');
        return 'granted' as const;
      },
      order: () => {
        steps.push('order');
        return { archetypes: ['cfo'], materialId: null, repeats: null, rehearsalName: null };
      },
      mint: async () => void steps.push('mint'),
    },
  };
}

it('discloses, then asks for the microphone, then mints', async () => {
  const { steps, deps } = trace();

  await enterRoom(deps);

  expect(steps).toEqual(['order', 'window', 'disclose', 'microphone', 'mint']);
});

it('does not disclose twice to the same person', async () => {
  const { steps, deps } = trace();

  await enterRoom(deps);
  steps.length = 0;
  await enterRoom(deps);

  expect(steps).toEqual(['order', 'microphone', 'mint']);
});

it('does not fetch the retention window it is not going to show', async () => {
  /**
   * A returning user taps this to start every rehearsal they ever do. A request
   * on that path for a number nothing will render is latency spent on nothing,
   * on the one tap the product asks people to make repeatedly.
   */
  const { steps, deps } = trace();

  await enterRoom(deps);
  steps.length = 0;
  await enterRoom(deps);

  expect(steps).not.toContain('window');
});

it('does not mint a session the microphone was refused for', async () => {
  /**
   * The ticket expires in seconds. Minting before the answer leaves somebody
   * who tapped "don't allow" holding a dead ticket against a live session that
   * has to be reaped rather than never created.
   */
  const { steps, deps } = trace();

  const outcome = await enterRoom({
    ...deps,
    ensureMicrophone: async () => {
      steps.push('microphone');
      return 'denied';
    },
  });

  expect(outcome).toBe('denied');
  expect(steps).not.toContain('mint');
});

it('remembers the disclosure even when the microphone is then refused', async () => {
  /**
   * They were told. Re-showing the sheet on the next attempt would imply they
   * had not been, and would make the refusal screen harder to reach than the
   * thing that caused it.
   */
  const { steps, deps } = trace();

  await enterRoom({ ...deps, ensureMicrophone: async () => 'denied' });
  steps.length = 0;
  await enterRoom(deps);

  expect(steps).not.toContain('disclose');
});

it('remembers the disclosure only once the person has actually continued', async () => {
  /**
   * Recorded after the sheet resolves, not before. Written first, an app killed
   * while the sheet was open would come back believing this person had been
   * told — and the sheet, being one-time, would never appear again. They would
   * be recorded from then on having read nothing.
   */
  const { deps } = trace();

  await expect(
    enterRoom({
      ...deps,
      disclose: async () => {
        throw new Error('the app went away');
      },
    })
  ).rejects.toThrow();

  expect(await deps.record.wasShownTo(ADA)).toBe(false);
});

it('does nothing at all when nobody asked for a room', async () => {
  // #76. `/interrogation` mints a metered session on mount, and until
  // 2026-08-20 the only thing gating that was an empty dependency array.
  // `app.json` declares the `flintroom` scheme and the route sits inside
  // `Stack.Protected guard={who === 'ready'}`, so `flintroom://interrogation`
  // opened a billed room for any signed-in person who followed a link — and a
  // remount did the same, because that guard re-evaluates whenever `who`
  // changes.
  //
  // The check belongs here rather than in the screen for the reason the rest of
  // this sequence does: it is an ordering rule, and it is the first one. Not
  // merely "do not mint" — do not present a sheet, and do not raise a system
  // permission prompt, at somebody who has not asked for anything.
  const { steps, deps } = trace();

  const outcome = await enterRoom({ ...deps, order: () => null });

  expect(outcome).toBe('unasked');
  expect(steps).toEqual([]);
});

it('hands the mint the seating it was asked for', async () => {
  // The seating used to travel as query params, which made the panel forgeable:
  // `flintroom://interrogation?archetypes=cfo` chose somebody's room for them,
  // and the bare link chose nothing, so the server seated a default panel the
  // presenter never picked. It rides in the order now, where no address can
  // reach it.
  const { deps } = trace();
  const seated: string[][] = [];

  await enterRoom({
    ...deps,
    order: () => ({ archetypes: ['champion', 'cfo'], materialId: 'deck-9', repeats: null, rehearsalName: null }),
    mint: async (order) => void seated.push(order.archetypes),
  });

  expect(seated).toEqual([['champion', 'cfo']]);
});
