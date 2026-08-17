/**
 * The design system, as values React Native can use.
 *
 * `design-guide/pitchgo_design_system/DESIGN.md` is brand truth (`Product.md`
 * §9) and `CLAUDE.md` forbids inventing values. This file is the copy that
 * makes them reachable from a StyleSheet — nothing more, and deliberately not a
 * place where new colours or sizes get decided.
 *
 * `tokens.test.ts` reads DESIGN.md and asserts the two agree, because the real
 * risk of a hand copy is not getting it wrong today. It is drifting quietly
 * later while every screen keeps rendering something that used to be right.
 *
 * Only what is in use is here. A token nobody renders is a value that has never
 * been looked at on a screen, and adding the whole palette up front is how
 * half a design system becomes untested.
 */

export const color = {
  /** The warm off-white ground. Not white — the whole world sits on this. */
  surface: '#fcf9f8',
  /** Cards and raised surfaces. Pure white, for the paper-on-surface read. */
  card: '#ffffff',
  /** Headings and primary content. */
  onSurface: '#1c1b1b',
  /**
   * Secondary text. Warm-tinted rather than gray, which is both what DESIGN.md
   * specifies and what stops body copy reading as disabled against a warm
   * ground.
   */
  onSurfaceVariant: '#5a4138',
  /** Hairlines and dividers. */
  hairline: '#e3bfb2',
  /** Burnt orange. Primary actions and brand moments, used sparingly. */
  primary: '#a43700',
  onPrimary: '#ffffff',
  /** Destructive actions only. Never decorative, never a status colour. */
  danger: '#ba1a1a',
} as const;

/**
 * The 4px baseline DESIGN.md builds everything on, named by use rather than by
 * t-shirt size so a caller picks a purpose instead of a number.
 */
export const space = {
  hair: 4,
  tight: 8,
  snug: 12,
  base: 16,
  loose: 24,
  section: 32,
  major: 48,
  /** The layout model's horizontal margin on mobile. */
  screen: 20,
} as const;

export const radius = {
  control: 12,
  card: 24,
  /** §9 names this one specifically as brand truth. */
  container: 28,
  /** Pill controls, per §9. */
  pill: 9999,
} as const;

/**
 * Hanken Grotesk throughout, per §9.
 *
 * **The weight is in the family name, and there is no `fontWeight`.** Android
 * does not synthesise weights for a custom family — it resolves the registered
 * name and ignores everything else — so a `fontWeight: '700'` beside a single
 * family would render headings at regular weight there and correctly on iOS,
 * which is the worst division of a bug there is.
 *
 * Every name here must be a key of `FONTS` in `fonts.ts`. Naming one that is
 * not loaded does not fail; it falls back to the system sans and the design
 * system quietly stops being the design system. `tokens.test.ts` is what makes
 * that a failure instead.
 */
export const type = {
  headlineLg: { fontFamily: 'HankenGrotesk_700Bold', fontSize: 32, lineHeight: 40, letterSpacing: -0.64 },
  headlineMd: { fontFamily: 'HankenGrotesk_600SemiBold', fontSize: 24, lineHeight: 32, letterSpacing: -0.24 },
  headlineSm: { fontFamily: 'HankenGrotesk_600SemiBold', fontSize: 20, lineHeight: 28 },
  bodyLg: { fontFamily: 'HankenGrotesk_400Regular', fontSize: 18, lineHeight: 28 },
  bodyMd: { fontFamily: 'HankenGrotesk_400Regular', fontSize: 16, lineHeight: 24 },
  bodySm: { fontFamily: 'HankenGrotesk_400Regular', fontSize: 14, lineHeight: 20 },
  labelLg: { fontFamily: 'HankenGrotesk_600SemiBold', fontSize: 14, lineHeight: 20 },
} as const;
