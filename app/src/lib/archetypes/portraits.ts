/**
 * A face for each archetype, in the bundle.
 *
 * Bundled rather than fetched. There are eight, they change roughly never, and
 * panel setup is the screen somebody opens before every single rehearsal — a
 * request per face would put eight round trips in front of the one screen that
 * has to feel instant, and leave the roster a grid of grey holes on a bad
 * connection.
 *
 * **Written out one by one because Metro requires it.** `require` is resolved
 * at build time from a string literal; `require(`./${name}.webp`)` compiles to
 * nothing and fails at runtime. A map is the honest version of that constraint
 * rather than a workaround for it — and it means an archetype added on the
 * server without artwork degrades to initials instead of crashing.
 *
 * WebP at 256px square: 76 KB for all eight, against roughly 830 KB as PNG.
 * The card renders them at 72pt, so 256 covers a 3× screen with room to spare.
 *
 * These are generated people, not photographs of anyone. That is the whole
 * reason they are permissible — `CLAUDE.md` locks archetypes to pre-built
 * personas precisely so no real person's likeness is ever involved. The set is
 * deliberately spread across age and ethnicity: any one of them alone is fine,
 * but eight lookalike executives would be the product quietly asserting what a
 * CFO looks like.
 *
 * **THE FACE MUST AGREE WITH THE VOICE, AND THE VOICE DECIDES.** Six of these
 * were originally hung on the wrong archetype, and it shipped: the architect
 * saw the CFO's picture and heard Daniel, a British male voice. Portraits are
 * artwork; `ELEVENLABS_VOICES` is shipped configuration carrying gender, accent
 * and age, and it predates them. So the pictures were reassigned to match the
 * casting rather than the casting re-cut to match the pictures.
 *
 * Who ended up where, and why — because the obvious repair is to shuffle them
 * again on taste, and that would break the thing this comment exists to hold:
 *
 * - `cfo` / Daniel, British male — the guarded, evaluating face. Reads as
 *   "not interested in vision until the arithmetic holds".
 * - `technical_skeptic` / Cecily, African American female — unimpressed and
 *   patient. The senior engineer who has watched confident demos fail.
 * - `champion` / Sarah, American female — the one leaning in. The only ally in
 *   the room has to look like one.
 * - `growth_maximalist` / Derrick, African American male — the youngest and
 *   most intense. Impatient with caution.
 * - `distracted_executive` / Adam, American male — open collar, faintly
 *   unbothered. Half-listening, deciding inside ninety seconds.
 * - `internal_blocker` / Lily, British female — unfailingly reasonable, mildly
 *   concerned, immovable.
 * - `customer_advocate` / Bella, American female — speaks for people who are
 *   not in the room.
 * - `risk_officer` / Bill, American older male — sober and still, comfortable
 *   being why it does not ship.
 *
 * Two were already right and were not moved: `internal_blocker` and
 * `risk_officer`.
 *
 * **The rule ran backwards once, on 2026-08-19, and only because the architect
 * said so.** These two seats were recast in African American voices to agree
 * with the faces that were already in them. That is not the rule failing: a
 * casting table is a decision by whoever owns the product, and the rule above
 * governs what an *engineer* may infer, which is that artwork never gets to
 * overrule shipped configuration on its own. `ELEVENLABS_VOICES` carries the
 * same note from the other side.
 */

/** Keyed by the archetype's slug, as `/v1/archetypes` and the wire spell it. */
const PORTRAITS: Record<string, number> = {
  cfo: require('../../../assets/archetypes/cfo.webp'),
  technical_skeptic: require('../../../assets/archetypes/technical_skeptic.webp'),
  champion: require('../../../assets/archetypes/champion.webp'),
  growth_maximalist: require('../../../assets/archetypes/growth_maximalist.webp'),
  distracted_executive: require('../../../assets/archetypes/distracted_executive.webp'),
  internal_blocker: require('../../../assets/archetypes/internal_blocker.webp'),
  customer_advocate: require('../../../assets/archetypes/customer_advocate.webp'),
  risk_officer: require('../../../assets/archetypes/risk_officer.webp'),
};

/**
 * Their face, or null when this build has none.
 *
 * Null rather than a stand-in image, so the card decides what absence looks
 * like — it falls back to initials, which say which archetype you are looking
 * at. A shared placeholder face would say the opposite.
 */
export function portraitOf(name: string): number | null {
  return PORTRAITS[name] ?? null;
}
