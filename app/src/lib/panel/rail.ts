import type { ArchetypeOffered } from '../api/panelsApi';
import type { MyArchetype } from '../api/archetypesApi';

/**
 * The eight we ship, plus the ones this account wrote.
 *
 * A pure function rather than a merge buried in the setup route, because the
 * ordering is a decision and a decision that only exists inside a `useEffect`
 * cannot be argued with.
 *
 * **Yours come last, and the shipped order never moves.** The rail is scrolled
 * from the left every time somebody assembles a room, and the eight are in the
 * order the reveal and the re-run path put them in — reordering that so a new
 * panelist could go first would move seven familiar cards to make room for one.
 * Yours accumulate at the end, next to the row that wrote them.
 *
 * `ArchetypeCard` needs no change to draw them: `portraitOf` answers null for a
 * name it does not know, and null is already the initials branch. A panelist
 * somebody wrote wears "BC" where a shipped one wears a face, which is also
 * what tells them at a glance whether the room still holds one of ours — the
 * floor the server enforces (`docs/custom-archetypes.md` §3).
 */
export function railFor(
  shipped: ArchetypeOffered[],
  mine: MyArchetype[]
): ArchetypeOffered[] {
  return [
    ...shipped,
    ...mine.map((one) => ({
      name: one.name,
      title: one.title,
      // Their own description. A shipped archetype's blurb exists so a picker
      // never prints the attack strategy — "a rehearsal the user has already
      // had" — and that reasoning is untouched: the strategy is ours and is not
      // in this text. What is shown back is what they wrote.
      blurb: one.persona,
    })),
  ];
}


/**
 * Whether this name belongs to a panelist somebody wrote.
 *
 * The prefix is minted server-side and enforced by a check constraint, so this
 * is a reliable test rather than a heuristic — the same guarantee `by_name`
 * leans on to keep two authorities out of one namespace.
 *
 * Duplicated from `agents/authored.CUSTOM_PREFIX` across the wire, which is
 * what a contract is. It is pinned by `test_the_prefix_is_the_same_string_in_
 * both_places` on the server and by the rail's own test here.
 */
export function isAuthored(name: string): boolean {
  return name.startsWith(AUTHORED_PREFIX);
}

/** What separates a row somebody owns from an archetype we ship. */
export const AUTHORED_PREFIX = 'custom:';
