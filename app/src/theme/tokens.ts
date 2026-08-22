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
  /**
   * The warm off-white ground. Not white — the whole world sits on this.
   *
   * **It was `#fcf9f8` and a white card on it measured 1.05:1**, which is below
   * the threshold of perception on a phone at a desk angle. Reported from a
   * device as "little contrast issue, clickable parts are not clearly
   * clickable", and the diagnosis was not the affordances: nothing on the
   * screen had an edge, so a card and the page it sat on were one surface.
   *
   * `hsl(20, 28%, 92%)` — the family's own hue, moving only saturation and
   * lightness, like the room's grounds. A white card now reads at **1.20:1**,
   * about 3.7× the luminance separation, which is the difference between a
   * sheet you cannot see and a sheet lying on a desk.
   *
   * **It does not reach 3:1 and nothing that stays an off-white can.** A ground
   * at WCAG 1.4.11's non-text floor against white needs a relative luminance
   * near 0.30 — roughly `#c2bab6`, a mid grey and not a canvas. So the boundary
   * is a *surface* relationship here, and every control still carries its own
   * affordance: a chevron where a row opens something, `primary` on a seated
   * card, a filled pill for a primary action.
   */
  surface: '#f0e9e5',
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
  /**
   * Hairlines and dividers.
   *
   * **Moved with the ground on 2026-08-22**, because it had to. `#e3bfb2` was
   * picked against a near-white canvas and measured 1.62:1 on it; darkening the
   * ground to `#f0e9e5` moved the canvas *toward* the rule and left it at
   * 1.42:1 — fainter than before, on the same pass that was meant to make
   * things visible. The rehearsal-name field on Home is a bare underline and
   * nothing else, so that regression would have landed on the one control the
   * change was supposed to help.
   *
   * `hsl(20, 22%, 66%)` — the family's hue again. A fine rule that reads on
   * both planes now: **2.41:1** on a card and **2.01:1** on the ground, against
   * 1.70 and 1.62 before. At `StyleSheet.hairlineWidth` that is a crisp
   * separator rather than a box, which is how the platform draws its own.
   */
  hairline: '#bba295',
  /** Burnt orange. Primary actions and brand moments, used sparingly. */
  primary: '#a43700',
  onPrimary: '#ffffff',
  /** Destructive actions only. Never decorative, never a status colour. */
  danger: '#ba1a1a',

  /**
   * The interrogation, and nowhere else.
   *
   * Every other surface in this app sits on `surface`. The live room does not,
   * and it is the single exception DESIGN.md carves out: the phone lies flat
   * on a desk for twelve minutes while somebody argues, and a page-bright
   * screen in that position is a lamp pointed at the ceiling. Setup, debrief
   * and sparring stay light — you go into the dark room, and you come out.
   *
   * Named `room*` rather than folded into the names above so that reaching for
   * one on a light screen reads as obviously wrong at the call site.
   *
   * Derived, not chosen: `primary` is hue 20°, and each of these holds that
   * hue and moves only saturation and lightness. The dark surface is a deeper
   * reading of the same identity rather than a second palette.
   */
  roomGround: '#15110f',
  /**
   * The same room, warmer — the panel is convinced. #74.
   *
   * **Warmer without being lighter**, and that is solved for rather than
   * chosen. `roomTrayLit` sits at 3.05:1 against the neutral ground, four
   * hundredths above the WCAG 2.2 non-text floor, so lightness is the one thing
   * this ground cannot spend: the obvious warm — `hsl(20, 26%, 10%)` — measures
   * 2.84:1 and would fail the speaking archetype's contrast only when the room
   * was going *well*.
   *
   * More saturation at hue 20 pushes green and blue down further than it pushes
   * red up, so this reads warmer and measures fractionally darker. The tray
   * reaches 3.08:1 against it.
   */
  roomGroundWarm: '#18100c',
  /**
   * The same room, cooled and dimmed toward gray — losing them. #74.
   *
   * Saturation out rather than a grey mixed in, so it is still the same hue at
   * the bottom of its range and not a second palette. 3.14:1 for the lit tray.
   */
  roomGroundCool: '#100f0e',
  /** An archetype who is seated and not speaking. */
  roomTray: '#413c3a',
  /**
   * The archetype holding the floor.
   *
   * 3:1 against `roomGround` — the WCAG 2.2 non-text contrast floor, solved
   * for rather than eyeballed.
   */
  roomTrayLit: '#675f5b',
  /** The line, at 16.5:1. `inverse-on-surface`, unchanged. */
  onRoom: '#f3f0ef',
  /**
   * Anything active on the dark ground, at 11:1. `inverse-primary`, unchanged
   * — the committed burnt orange as this system already renders it on dark.
   */
  roomAmber: '#ffb59a',
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
