import type { TokenPair, TokenStore } from './tokens';

/**
 * The signed-in session, across a refresh token that rotates under it.
 *
 * The server spends a refresh token on use and treats a replay as theft: it
 * revokes the whole family and ends the session everywhere. It cannot tell a
 * thief from a client that asked twice — the thief may have rotated first,
 * leaving the real user holding the spent one — so the only safe client is one
 * that never presents the same refresh token twice.
 */

/**
 * The session is over and cannot be recovered without signing in again.
 *
 * Distinct from a network failure on purpose: one means show the sign-in
 * screen, the other means try again in a moment, and treating the second as
 * the first would throw users out every time a lift door closed.
 */
/**
 * How long before expiry a token is treated as already gone.
 *
 * A token with seconds left passes the check and expires before the request
 * lands — routine on a phone, where a call can sit waiting for the radio to
 * wake. The result is a 401 on a request that was checked and passed. Thirty
 * seconds against a fifteen-minute token costs one extra refresh every few
 * hours and removes the whole class of failure.
 */
const EXPIRY_SKEW_MS = 30_000;

export class SignedOut extends Error {
  constructor(reason: string) {
    super(reason);
    this.name = 'SignedOut';
  }
}

/** What the server hands back, before it is given an absolute expiry. */
export interface IssuedTokens {
  accessToken: string;
  refreshToken: string;
  /** Seconds, as the wire carries it. */
  expiresIn: number;

  /**
   * Whether this sign-in called off a scheduled account deletion.
   *
   * `docs/account-deletion.md` decision 5, and the caller owes the user a
   * sentence when it is true — an account that quietly un-deletes itself is
   * worse than one that stayed deleted, because they never learn their data is
   * still there. `CANCELLED_ON_SIGN_IN` in `lib/account/deletion.ts` is the
   * sentence.
   *
   * Always false from a refresh, which is not somebody coming back.
   */
  deletionCancelled: boolean;
}

/** What a completed sign-in has to say for itself. */
export interface Admission {
  /** True when this sign-in reversed a pending deletion. Say so. */
  deletionCancelled: boolean;
}

/**
 * The plan somebody filled in before they had an account.
 *
 * Camel-cased here and snake-cased on the wire by `authApi`, which is the one
 * place that translation is allowed to live. Every field optional, because the
 * survey can be abandoned at any point and still produce an account — a
 * required field would turn "I skipped a question" into "sign-in failed", at
 * the moment somebody has spent five answers and has nothing yet to show.
 */
export interface OnboardingPlan {
  situation: string | null;
  happensOn: string | null;
  role: string | null;
  audience: string[];
}

export interface AuthApi {
  signIn(
    provider: string,
    idToken: string,
    plan?: OnboardingPlan
  ): Promise<IssuedTokens>;
  refresh(refreshToken: string): Promise<IssuedTokens>;
  /** Revokes the family server-side. Takes the refresh token, not a bearer. */
  signOut(refreshToken: string): Promise<void>;
}

export interface AuthSession {
  /**
   * Resolves with what the sign-in did besides letting them in.
   *
   * `plan` rides the *same request* rather than following it, because
   * `docs/onboarding.md` refuses the state a second call allows: an account
   * that exists and has been asked nothing. Omitted on every launch after the
   * first — a missing plan means "nothing new to say", never "forget what I
   * told you", and there is a server test for exactly that.
   */
  signIn(provider: string, idToken: string, plan?: OnboardingPlan): Promise<Admission>;
  /** A token good to send now, refreshing first if the stored one has expired. */
  accessToken(): Promise<string>;
  /** Ends the session here and, if reachable, everywhere. Never rejects. */
  signOut(): Promise<void>;
}

export interface AuthSessionOptions {
  api: AuthApi;
  store: TokenStore;
  /** Injected so expiry is testable without waiting fifteen minutes. */
  now?: () => number;
}

export function createAuthSession({
  api,
  store,
  now = Date.now,
}: AuthSessionOptions): AuthSession {
  /**
   * The single in-flight refresh, or null.
   *
   * Callers share one promise rather than each starting a refresh. This is the
   * whole reason this module exists: a screen that mounts and fires three
   * requests at once would otherwise present the same refresh token three
   * times, and the second presentation is what the server reads as theft.
   */
  let refreshing: Promise<TokenPair> | null = null;

  const persist = async (issued: IssuedTokens): Promise<TokenPair> => {
    const pair: TokenPair = {
      accessToken: issued.accessToken,
      refreshToken: issued.refreshToken,
      // Absolute, and computed once here. Kept as a duration it would have to
      // be interpreted against whenever it was later read, which is a clock
      // the app does not control across a suspend.
      expiresAt: now() + issued.expiresIn * 1000,
    };

    await store.save(pair);

    return pair;
  };

  /** Spend the refresh token exactly once, and let everyone waiting share it. */
  const refresh = (refreshToken: string): Promise<TokenPair> => {
    const attempt = (async () => {
      try {
        return await persist(await api.refresh(refreshToken));
      } catch (error) {
        // Only a refusal clears the pair, and the distinction is the whole
        // point of the two error types. A revoked family can never work
        // again, so keeping it means presenting a dead token on every launch
        // forever — each attempt another reuse report in the server's log. A
        // network failure is a tunnel: clearing there would sign the user out
        // for walking into a lift, permanently, since the refresh token is
        // the only way back.
        if (error instanceof SignedOut) {
          await store.clear();
        }

        throw error;
      }
    })();

    // Cleared on settle, success or failure. Left set after a failure, a
    // transient network error would pin every later caller to the same dead
    // promise for the life of the process.
    return attempt.finally(() => {
      refreshing = null;
    });
  };

  return {
    signIn: async (provider, idToken, plan) => {
      const admitted = await api.signIn(provider, idToken, plan);
      await persist(admitted);

      // Passed up rather than acted on here. This module owns credentials; a
      // sentence on a screen is not its business, and one told from inside
      // could not be tested without a renderer.
      return { deletionCancelled: admitted.deletionCancelled };
    },

    signOut: async () => {
      const stored = await store.load();

      if (stored !== null) {
        try {
          await api.signOut(stored.refreshToken);
        } catch {
          // Swallowed, and only here. Sign-out must never fail from the
          // user's side: offline, the family outlives the local credentials,
          // but the alternative is a button that refuses to work on a train,
          // on a device the user may be about to hand back.
        }
      }

      await store.clear();
    },

    accessToken: async () => {
      const stored = await store.load();

      if (stored === null) {
        throw new SignedOut('no stored credentials');
      }

      if (stored.expiresAt > now() + EXPIRY_SKEW_MS) {
        return stored.accessToken;
      }

      // Assigned before anything is awaited, which is the entire trick. The
      // obvious spelling — `refreshing ??= persist(await api.refresh(...))` —
      // awaits the network call *before* the assignment, so every caller
      // passes the null check before any of them records that a refresh is
      // running. It reads as single-flight and behaves as a stampede.
      if (refreshing === null) {
        refreshing = refresh(stored.refreshToken);
      }

      return (await refreshing).accessToken;
    },
  };
}
