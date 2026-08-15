/**
 * The credential pair, between launches.
 *
 * Stored in the keychain rather than plain storage, because a refresh token is
 * a long-lived credential and the only thing standing between a stolen device
 * backup and someone else's rehearsals.
 */

/**
 * One key holding both tokens, not one key each.
 *
 * The server rotates the refresh token on use and treats a replay as theft,
 * revoking the whole family. A pair half-written — new access token beside the
 * spent refresh token — is therefore not a degraded state that could be
 * repaired on next launch; it is a session already lost. A single value cannot
 * be half-written.
 */
const KEY = 'flintroom.auth.pair';

export interface TokenPair {
  accessToken: string;
  refreshToken: string;
  /** Epoch milliseconds. Absolute, so it survives a process that slept. */
  expiresAt: number;
}

/** The slice of `expo-secure-store` this needs. Structural, so tests need no native. */
export interface SecureStorage {
  getItemAsync(key: string): Promise<string | null>;
  setItemAsync(key: string, value: string): Promise<void>;
  deleteItemAsync(key: string): Promise<void>;
}

export interface TokenStore {
  load(): Promise<TokenPair | null>;
  save(pair: TokenPair): Promise<void>;
  clear(): Promise<void>;
}

export function createTokenStore(storage: SecureStorage): TokenStore {
  return {
    load: async () => {
      const stored = await storage.getItemAsync(KEY);

      if (stored === null) {
        return null;
      }

      try {
        return JSON.parse(stored) as TokenPair;
      } catch {
        // Unreadable means signed out, not broken. Thrown from here it would
        // be thrown on every launch, and the code that would clear the bad
        // value sits behind the crash.
        return null;
      }
    },

    save: async (pair) => {
      try {
        await storage.setItemAsync(KEY, JSON.stringify(pair));
      } catch (error) {
        // The previous pair must not survive a failed write. Its refresh
        // token may already have been spent to obtain the one that failed to
        // save, and presenting a spent token is what the server reads as
        // theft — it revokes the family and signs the user out everywhere.
        // Signing in again is a worse morning than being locked out of every
        // device, so the stale value goes.
        await storage.deleteItemAsync(KEY);
        throw error;
      }
    },

    clear: () => storage.deleteItemAsync(KEY),
  };
}
