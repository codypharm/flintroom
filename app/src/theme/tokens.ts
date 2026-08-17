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
 * The family name is the loaded font's PostScript-ish name rather than the
 * display name in DESIGN.md — React Native resolves the face by what was
 * registered, and "Hanken Grotesk" with a space silently falls back to the
 * system sans on Android, which is a whole design system quietly not
 * rendering.
 */
export const type = {
  headlineLg: { fontFamily: 'HankenGrotesk', fontSize: 32, fontWeight: '700', lineHeight: 40, letterSpacing: -0.64 },
  headlineMd: { fontFamily: 'HankenGrotesk', fontSize: 24, fontWeight: '600', lineHeight: 32, letterSpacing: -0.24 },
  headlineSm: { fontFamily: 'HankenGrotesk', fontSize: 20, fontWeight: '600', lineHeight: 28 },
  bodyLg: { fontFamily: 'HankenGrotesk', fontSize: 18, fontWeight: '400', lineHeight: 28 },
  bodyMd: { fontFamily: 'HankenGrotesk', fontSize: 16, fontWeight: '400', lineHeight: 24 },
  bodySm: { fontFamily: 'HankenGrotesk', fontSize: 14, fontWeight: '400', lineHeight: 20 },
  labelLg: { fontFamily: 'HankenGrotesk', fontSize: 14, fontWeight: '600', lineHeight: 20 },
} as const;
