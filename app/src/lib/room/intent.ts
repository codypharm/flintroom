/**
 * The order to open a metered room, held in memory and spent on arrival.
 *
 * `/interrogation` mints a billed session on mount. Until 2026-08-20 the only
 * thing gating that was an empty dependency array, which is not a gate at all:
 *
 * - `app.json` declares the `flintroom` scheme and the route is registered
 *   inside `Stack.Protected guard={who === 'ready'}`, so
 *   `flintroom://interrogation` opened a paid room for any signed-in person who
 *   tapped a link — with no archetypes, so the server seated a default panel
 *   nobody chose.
 * - `Stack.Protected` re-evaluates its guard whenever `who` changes. A token
 *   refresh that flips off `'ready'` and back unmounts and remounts the
 *   subtree, and a remount ran the mint again.
 *
 * Neither is a double charge — the server refuses a concurrent second start
 * with `active_session_exists` and audits the denial — but both are one room
 * the presenter did not ask for, and `CLAUDE.md` puts the metering boundary
 * outside the set of things that may be got wrong.
 *
 * **Why a carrier and not a check.** A check answers "was this allowed?" and
 * has to enumerate the ways in. This answers "what was I asked to do?", and a
 * route reached any other way has no answer to give. Module state dies with the
 * JS context, so a cold start inherits nothing; `take` clears it, so a remount
 * finds nothing.
 *
 * **The seating rides along rather than travelling in the URL.** That is what
 * makes the panel unforgeable: the address bar no longer names it, so there is
 * no string a link can carry to seat somebody's room for them.
 *
 * Not persisted, deliberately. Surviving a cold start is the property we are
 * removing — a room that outlives the tap is the bug.
 *
 * @see lib/room/closing.ts for the other half of a room's lifetime.
 */

/** What one tap on Start asked for. */
export interface RoomOrder {
  /** Archetype names, in seating order. Chair one speaks first. */
  archetypes: string[];

  /** The attached deck, or null when the room is being run on speech alone. */
  materialId: string | null;

  /**
   * The room this one is a re-run of, or null when the argument is a new one.
   *
   * A room id rather than a lineage id, because the server has to be able to
   * *check* it: "which room this repeats" is a claim it verifies against
   * ownership, and a group id taken from a request would let a rehearsal be
   * filed into somebody else's history. The server resolves the lineage.
   *
   * Not part of the forgery surface the rest of this module exists about. A
   * link that named a room id could only join a lineage the person already
   * owns — a mis-filed rehearsal, not a room nobody asked for — and it still
   * takes a tap on Start to spend it.
   */
  repeats: string | null;
}

/**
 * Held rather than queued: two taps with no room between them are one
 * intention, and the later seating is the one in front of the person.
 */
let held: RoomOrder | null = null;

/** Called by the control that starts a room, immediately before navigating. */
export function intendRoom(order: RoomOrder): void {
  held = order;
}

/**
 * The order, once, or null if this route was reached some other way.
 *
 * Clears on read. A caller that gets null has not been refused a room — it has
 * discovered that nobody asked for one, which is a different thing and wants a
 * different answer: go to where rooms are started, not an error.
 */
export function takeIntent(): RoomOrder | null {
  const order = held;
  held = null;
  return order;
}
