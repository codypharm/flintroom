import { createTokenStore, type TokenPair } from './tokens';
import { createAuthSession, SignedOut } from './session';

/**
 * Holding a session open across a rotating refresh token.
 *
 * The server rotates the refresh token on every use and treats a *replay* as
 * theft: presenting a spent token revokes the whole family and ends the
 * session on every device (`backend/app/modules/auth/refresh.py`). It cannot
 * tell a thief from a client that asked twice, and deliberately so — the thief
 * may have rotated first, leaving the victim holding the spent one.
 *
 * That single fact decides the design here. Two requests that both find an
 * expired access token must produce **one** refresh, or the app signs the user
 * out by racing itself, at random, under exactly the conditions a real screen
 * creates: several calls firing together when it mounts.
 */
class FakeStorage {
  readonly items = new Map<string, string>();

  async getItemAsync(key: string) {
    return this.items.get(key) ?? null;
  }
  async setItemAsync(key: string, value: string) {
    this.items.set(key, value);
  }
  async deleteItemAsync(key: string) {
    this.items.delete(key);
  }
}

/** A refresh endpoint that rotates, and that notices a token spent twice. */
class FakeAuthApi {
  refreshCalls: string[] = [];
  signInCalls: { provider: string; idToken: string }[] = [];
  signOutCalls: string[] = [];

  async signOut(refreshToken: string) {
    this.signOutCalls.push(refreshToken);
  }

  private readonly spent = new Set<string>();
  private issued = 0;

  async signIn(provider: string, idToken: string) {
    this.signInCalls.push({ provider, idToken });
    return this.issue();
  }

  async refresh(refreshToken: string) {
    this.refreshCalls.push(refreshToken);

    if (this.spent.has(refreshToken)) {
      // What the real server does on a replay: the family dies.
      throw new SignedOut('refresh token reused');
    }
    this.spent.add(refreshToken);

    return this.issue();
  }

  private issue() {
    this.issued += 1;
    return {
      accessToken: `access-${this.issued}`,
      refreshToken: `refresh-${this.issued}`,
      expiresIn: 900,
      // The ordinary case, and the only one this file cares about: nobody in
      // here had a deletion pending. What a sign-in does with the flag is
      // `authApi`'s translation and `lib/account/deletion.ts`'s sentence.
      deletionCancelled: false,
    };
  }
}

const NOW = 1_700_000_000_000;

function session(stored: TokenPair | null = null) {
  const storage = new FakeStorage();
  const api = new FakeAuthApi();
  const store = createTokenStore(storage);

  if (stored) {
    storage.items.set('flintroom.auth.pair', JSON.stringify(stored));
  }

  return {
    api,
    store,
    auth: createAuthSession({ api, store, now: () => NOW }),
  };
}

const live: TokenPair = {
  accessToken: 'access-live',
  refreshToken: 'refresh-live',
  expiresAt: NOW + 600_000,
};

const expired: TokenPair = {
  accessToken: 'access-old',
  refreshToken: 'refresh-old',
  expiresAt: NOW - 1,
};

describe('signing in', () => {
  it('exchanges the provider token and keeps the pair', async () => {
    const { auth, api, store } = session();

    await auth.signIn('apple', 'apple-id-token');

    expect(api.signInCalls).toEqual([{ provider: 'apple', idToken: 'apple-id-token' }]);
    await expect(store.load()).resolves.toMatchObject({ refreshToken: 'refresh-1' });
  });
});

describe('presenting an access token', () => {
  it('uses the stored one while it is still good', async () => {
    const { auth, api } = session(live);

    await expect(auth.accessToken()).resolves.toBe('access-live');
    expect(api.refreshCalls).toEqual([]);
  });

  it('refreshes an expired one, and stores both halves of the new pair', async () => {
    // "Always store both" is the contract: the refresh token rotates, so a
    // client that keeps the old one is a replay waiting to happen.
    const { auth, store } = session(expired);

    await expect(auth.accessToken()).resolves.toBe('access-1');
    await expect(store.load()).resolves.toMatchObject({
      accessToken: 'access-1',
      refreshToken: 'refresh-1',
    });
  });

  it('refreshes a token that is about to expire, not merely one that has', async () => {
    // A token with seconds left is valid when the decision is made and expired
    // by the time the request lands — on a phone, where a request can sit
    // waiting for a radio to wake up. The failure is a 401 on a call that was
    // checked and passed, which reads as the server being wrong.
    const { auth, api } = session({ ...live, expiresAt: NOW + 20_000 });

    await auth.accessToken();

    expect(api.refreshCalls).toEqual(['refresh-live']);
  });

  it('refreshes once when several callers arrive together', async () => {
    // The failure this prevents is not theoretical: a screen that mounts and
    // fires three requests at once is the normal case. Without this, two of
    // them present the same refresh token, the server sees a replay, and the
    // user is signed out of every device by an app talking to itself.
    const { auth, api } = session(expired);

    const tokens = await Promise.all([auth.accessToken(), auth.accessToken(), auth.accessToken()]);

    expect(api.refreshCalls).toEqual(['refresh-old']);
    expect(tokens).toEqual(['access-1', 'access-1', 'access-1']);
  });
});

describe('signing out', () => {
  it('tells the server, then forgets the pair', async () => {
    // The server call is what revokes the family. Skipping it would leave a
    // valid refresh token alive on a device the user believes they have signed
    // out of — which is exactly what someone signing out on a borrowed phone
    // is trying to prevent.
    const { auth, api, store } = session(live);

    await auth.signOut();

    expect(api.signOutCalls).toEqual(['refresh-live']);
    await expect(store.load()).resolves.toBeNull();
  });

  it('forgets the pair even when the server cannot be reached', async () => {
    // Sign-out must never fail from the user's side. Offline, the local
    // credentials still go; the family outlives them, but the alternative is a
    // button that refuses to work on a train, on a device the user may be
    // handing back.
    const { auth, api, store } = session(live);
    api.signOut = async () => {
      throw new Error('network request failed');
    };

    await expect(auth.signOut()).resolves.toBeUndefined();
    await expect(store.load()).resolves.toBeNull();
  });
});

describe('when the refresh is refused', () => {
  it('forgets the pair, because it can never work again', async () => {
    // The family is revoked server-side. Keeping the tokens would mean
    // presenting a dead refresh token on every launch forever, and each
    // attempt is another reuse report in the server's logs.
    const { auth, api, store } = session(expired);
    api.refresh = async () => {
      throw new SignedOut('refresh token reused');
    };

    await expect(auth.accessToken()).rejects.toBeInstanceOf(SignedOut);
    await expect(store.load()).resolves.toBeNull();
  });

  it('keeps the pair when the network is merely down', async () => {
    // A tunnel is not a revocation. Clearing here would sign the user out for
    // walking into a lift — and, because the refresh token is the only way
    // back, would make it permanent.
    const { auth, api, store } = session(expired);
    api.refresh = async () => {
      throw new Error('network request failed');
    };

    await expect(auth.accessToken()).rejects.toThrow('network request failed');
    await expect(store.load()).resolves.toMatchObject({ refreshToken: 'refresh-old' });
  });

  it('lets a later caller try again after a network failure', async () => {
    // The in-flight promise is cleared on failure as well as success. Left
    // set, every caller for the life of the process would await the same dead
    // promise, and the app would stay signed out until it was restarted.
    const { auth, api } = session(expired);
    const working = api.refresh.bind(api);
    api.refresh = async () => {
      throw new Error('network request failed');
    };

    await expect(auth.accessToken()).rejects.toThrow();
    api.refresh = working;

    await expect(auth.accessToken()).resolves.toBe('access-1');
  });
});
