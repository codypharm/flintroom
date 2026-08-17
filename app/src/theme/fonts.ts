import {
  HankenGrotesk_400Regular,
  HankenGrotesk_600SemiBold,
  HankenGrotesk_700Bold,
} from '@expo-google-fonts/hanken-grotesk';

/**
 * The brand face, actually loaded.
 *
 * `Product.md` §9 makes Hanken Grotesk brand truth, and until this existed the
 * type tokens named a family the app had never loaded — which does not fail. It
 * falls back to the system sans, silently, on every screen, and the design
 * system quietly stops being the design system.
 *
 * **One family per weight, rather than one family and a `fontWeight`.** Android
 * does not synthesise weights for a custom family: it resolves the registered
 * name and ignores the rest, so a single `HankenGrotesk` family would render
 * every heading at regular weight on half the devices we ship to. iOS is more
 * forgiving, which is worse — the bug would only appear on the platform nobody
 * develops on.
 *
 * Three weights, not nine. `tokens.ts` uses 400, 600 and 700; the rest of the
 * family is real but unused, and bundling a face nobody renders is app size
 * spent on nothing.
 */
export const FONTS = {
  HankenGrotesk_400Regular,
  HankenGrotesk_600SemiBold,
  HankenGrotesk_700Bold,
} as const;

/** The family names `tokens.ts` may name. Anything else is a silent fallback. */
export type LoadedFont = keyof typeof FONTS;
