import { createDisclosureRecord, type DisclosureStorage } from './disclosure';

/**
 * Who has been told that their rooms are saved.
 *
 * `docs/session-retention.md` chose on-by-default with a disclosure rather than
 * opt-in, which puts the whole weight of the decision on the disclosure
 * actually happening. A sheet that silently stops appearing is the failure that
 * matters here, and it is invisible from inside the app.
 */

class FakeStore implements DisclosureStorage {
  private readonly values = new Map<string, string>();
  public writes = 0;

  async getItemAsync(key: string) {
    return this.values.get(key) ?? null;
  }

  async setItemAsync(key: string, value: string) {
    this.writes += 1;
    this.values.set(key, value);
  }
}

const ADA = 'e6f1c0d2-0000-4000-8000-000000000001';
const GRACE = 'e6f1c0d2-0000-4000-8000-000000000002';

it('has told nobody anything on a fresh install', async () => {
  const record = createDisclosureRecord(new FakeStore());

  expect(await record.wasShownTo(ADA)).toBe(false);
});

it('remembers the person it was shown to', async () => {
  const record = createDisclosureRecord(new FakeStore());

  await record.rememberShownTo(ADA);

  expect(await record.wasShownTo(ADA)).toBe(true);
});

it('has not told the next person to sign in on the same phone', async () => {
  /**
   * Keyed by account, not by install. Consent belongs to a person, and a shared
   * or handed-on device would otherwise let somebody's first interrogation be
   * recorded without them ever having been told — which is precisely the claim
   * the disclosure exists to make true.
   */
  const record = createDisclosureRecord(new FakeStore());

  await record.rememberShownTo(ADA);

  expect(await record.wasShownTo(GRACE)).toBe(false);
});

it('treats an unreadable record as nobody having been told', async () => {
  /**
   * Deny by default, in the direction that costs a second sheet rather than a
   * missed disclosure. Storage that has been corrupted, cleared or migrated
   * cannot prove anybody was told, and showing it again is a mild annoyance
   * where skipping it is a promise quietly broken.
   */
  const store = new FakeStore();
  await store.setItemAsync('flintroom.consent.recording', 'not json');

  const record = createDisclosureRecord(store);

  expect(await record.wasShownTo(ADA)).toBe(false);
});

it('does not rewrite storage for somebody already told', async () => {
  /**
   * Entering a room is the hot path, and this is read on every one of them.
   * A keychain write per room is work nothing asked for.
   */
  const store = new FakeStore();
  const record = createDisclosureRecord(store);

  await record.rememberShownTo(ADA);
  await record.rememberShownTo(ADA);

  expect(store.writes).toBe(1);
});
