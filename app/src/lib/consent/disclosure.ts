/**
 * Who has been told that their rooms are saved.
 *
 * `docs/session-retention.md` decided recording is on by default and disclosed
 * up front, rather than opt-in — the reasoning being that most people never
 * open Settings, so an opt-in builds a compounding cost centre the majority
 * never switch on and leaves "come back and play it" broken for almost
 * everyone.
 *
 * That decision puts the entire weight of the thing on the disclosure actually
 * happening. What stores require for a recording somebody is themselves making
 * is disclosure and control, not consent — and a sheet that quietly stops
 * appearing turns a defensible default into an undisclosed one, with nothing
 * inside the app looking any different.
 */

const KEY = 'flintroom.consent.recording';

/**
 * The slice of `expo-secure-store` this needs. Structural, so tests need no
 * native — the same seam `createTokenStore` uses.
 *
 * The keychain rather than a new storage dependency, and the reasoning is
 * mundane: this is not a secret, but it is one small value on a device that
 * already has somewhere safe to put small values. `CLAUDE.md` asks that a new
 * dependency justify itself against what it replaces, and "a flag that could
 * live in a store we already have" does not clear that bar.
 */
export interface DisclosureStorage {
  getItemAsync(key: string): Promise<string | null>;
  setItemAsync(key: string, value: string): Promise<void>;
}

export interface DisclosureRecord {
  wasShownTo(userId: string): Promise<boolean>;
  rememberShownTo(userId: string): Promise<void>;
}

/** Account ids that have seen the sheet on this install. */
type Told = Record<string, true>;

export function createDisclosureRecord(
  storage: DisclosureStorage
): DisclosureRecord {
  const read = async (): Promise<Told> => {
    const stored = await storage.getItemAsync(KEY);

    if (stored === null) {
      return {};
    }

    try {
      return JSON.parse(stored) as Told;
    } catch {
      // Unreadable means nobody has been told. Deny by default, in the
      // direction that costs a second sheet rather than a missed disclosure:
      // showing it twice is an annoyance, skipping it is a promise quietly
      // broken and unprovable afterwards.
      return {};
    }
  };

  return {
    wasShownTo: async (userId) => (await read())[userId] === true,

    rememberShownTo: async (userId) => {
      const told = await read();

      if (told[userId] === true) {
        // Entering a room reads this every time. A keychain write per room is
        // work nothing asked for.
        return;
      }

      // Keyed by account rather than by install. Consent belongs to a person,
      // and a shared or handed-on phone would otherwise let somebody's first
      // interrogation be recorded without them ever having been told — exactly
      // the claim this record exists to keep true.
      await storage.setItemAsync(KEY, JSON.stringify({ ...told, [userId]: true }));
    },
  };
}
