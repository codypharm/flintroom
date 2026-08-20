/**
 * The Flintroom mark, and the one number needed to draw it.
 *
 * Extracted when the second screen wanted it. `SignInSheet` held these
 * privately while it was the only place the mark appeared; the shared top bar
 * is the second, and two copies of a measured constant is how the wordmark and
 * the app bar come to disagree about the size of the same logo.
 *
 * `splash-icon.png` rather than `icon.png`: it is the transparent output of
 * `scripts/build-icons.mjs`, so it composites onto whatever ground it lands on.
 * `icon.png` is the same mark flattened onto `color.surface`, which is
 * invisible on a screen and a warm square on a card.
 *
 * **The framing is measured, not assumed.** That file is a 1024² canvas holding
 * a mark whose alpha bounding box is 477×552, centred to the pixel — so
 * `resizeMode="contain"` inside a square box draws it at 53.9% of the box
 * height and 46.6% of its width. Divide the mark height you want by `FILLS` to
 * get the box. Re-derive if the framing ever changes; `build-icons.mjs` prints
 * the bounding box every time it runs.
 */

export const MARK = require('../../../assets/images/splash-icon.png');

/** How much of a square box the mark's own height fills under `contain`. */
export const FILLS = 0.539;

/** And its width, which is the smaller of the two — the mark is taller than wide. */
export const FILLS_WIDE = 0.466;

/** The box that draws a mark of `height` points. */
export function boxFor(height: number): number {
  return Math.round(height / FILLS);
}

/**
 * The transparent margin the asset carries on each side of the visible mark.
 *
 * **Subtract this or a lockup lies about its own spacing.** At a 41pt box the
 * mark is only 19pt wide, so 11pt of nothing sits either side of it — a `gap`
 * of 8 between mark and wordmark then reads as 19, and the lockup starts 11pt
 * inside the screen margin it was aligned to. A negative `marginHorizontal` of
 * this size pulls the box back to the ink.
 *
 * Cheaper than re-exporting a tightly cropped asset, and honest for the same
 * reason the framing constants are: the number is measured from the file.
 */
export function padFor(box: number): number {
  return Math.round((box * (1 - FILLS_WIDE)) / 2);
}
