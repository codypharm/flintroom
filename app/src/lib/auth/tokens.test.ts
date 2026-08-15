import type * as SecureStore from 'expo-secure-store';

import { createTokenStore, type SecureStorage } from './tokens';

/** The real module satisfies the interface, asserted by the typechecker. */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function theRealStoreFits(store: typeof SecureStore): SecureStorage {
  return store;
}

/**
 * Where the credential pair lives between launches.
 *
 * The refresh token is a long-lived credential, so it belongs in the keychain
 * and never in plain storage. The pair is also written and read as one value:
 * the server rotates the refresh token on use and treats a replay as theft,
 * revoking the whole family (`backend/app/modules/auth/refresh.py`). Half a
 * saved pair is therefore not a degraded state to recover from — it is a
 * session that is already gone.
 */
class FakeSecureStore {
  readonly items = new Map<string, string>();
  failNextWrite = false;

  async getItemAsync(key: string): Promise<string | null> {
    return this.items.get(key) ?? null;
  }

  async setItemAsync(key: string, value: string): Promise<void> {
    if (this.failNextWrite) {
      this.failNextWrite = false;
      throw new Error('keychain unavailable');
    }
    this.items.set(key, value);
  }

  async deleteItemAsync(key: string): Promise<void> {
    this.items.delete(key);
  }
}

const pair = {
  accessToken: 'access-1',
  refreshToken: 'refresh-1',
  expiresAt: 1_700_000_000_000,
};

describe('keeping the credential pair', () => {
  it('reads back what it stored', async () => {
    const store = createTokenStore(new FakeSecureStore());

    await store.save(pair);

    await expect(store.load()).resolves.toEqual(pair);
  });

  it('reports no pair rather than an empty one when nothing is stored', async () => {
    // First launch, and every launch after a sign-out. The caller branches on
    // null to decide between the sign-in screen and the app.
    const store = createTokenStore(new FakeSecureStore());

    await expect(store.load()).resolves.toBeNull();
  });

  it('forgets the pair on sign-out', async () => {
    const store = createTokenStore(new FakeSecureStore());

    await store.save(pair);
    await store.clear();

    await expect(store.load()).resolves.toBeNull();
  });

  it('treats unreadable storage as signed out rather than crashing', async () => {
    // A garbled value has to mean "sign in again", not an exception on the
    // launch path. Thrown here it would be thrown on every subsequent launch
    // too — an app that cannot start and cannot be repaired from inside,
    // because the code that would clear the bad value is behind the crash.
    const storage = new FakeSecureStore();
    storage.items.set('flintroom.auth.pair', 'not json');

    await expect(createTokenStore(storage).load()).resolves.toBeNull();
  });

  it('does not leave a stale pair behind when a write fails', async () => {
    // A failed keychain write must not leave the previous pair readable. Its
    // refresh token may already have been spent to obtain the one that failed
    // to save, and presenting a spent token is what the server reads as theft
    // — it revokes the family and signs the user out of every device.
    const storage = new FakeSecureStore();
    const store = createTokenStore(storage);

    await store.save(pair);
    storage.failNextWrite = true;

    await expect(store.save({ ...pair, refreshToken: 'refresh-2' })).rejects.toThrow();
    await expect(store.load()).resolves.toBeNull();
  });
});
