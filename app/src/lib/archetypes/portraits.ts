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
 * deliberately spread across age, gender and ethnicity: any one of them alone
 * is fine, but eight lookalike executives would be the product quietly
 * asserting what a CFO looks like.
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
