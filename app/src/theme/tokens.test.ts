import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { FONTS } from './fonts';
import { color, radius, space, type } from './tokens';

/**
 * The tokens, checked against the file that owns them.
 *
 * `Product.md` §9 makes `design-guide/pitchgo_design_system/DESIGN.md` binding
 * brand truth, and `CLAUDE.md` forbids inventing values. Copying them into
 * TypeScript is unavoidable — React Native cannot read YAML at runtime — so the
 * risk is not the copy, it is the copy going stale silently while every screen
 * keeps rendering something that was once correct.
 */

const DESIGN = readFileSync(
  join(__dirname, '../../../design-guide/pitchgo_design_system/DESIGN.md'),
  'utf8'
);

function documented(key: string): string {
  const found = DESIGN.match(new RegExp(`^  ${key}: '?([^'\\n]+)'?$`, 'm'));

  if (found === null) {
    throw new Error(`${key} is not in DESIGN.md`);
  }

  return found[1];
}

it.each([
  ['surface', () => color.surface],
  ['on-surface', () => color.onSurface],
  ['on-surface-variant', () => color.onSurfaceVariant],
  ['surface-container-lowest', () => color.card],
  ['outline-variant', () => color.hairline],
  ['primary', () => color.primary],
  ['on-primary', () => color.onPrimary],
  ['error', () => color.danger],
])('takes %s straight from DESIGN.md', (key, actual) => {
  expect(actual()).toBe(documented(key));
});

it('keeps the 4px baseline the spacing scale is built on', () => {
  /**
   * DESIGN.md: "every element — from the height of a button to the padding of a
   * card — is a multiple of 4". A scale that drifts off it loses the property
   * that makes it a scale rather than a list of numbers somebody liked.
   */
  for (const value of Object.values(space)) {
    expect(value % 4).toBe(0);
  }
});

it('carries the container padding the layout model specifies', () => {
  expect(space.screen).toBe(20);
});

it('names only fonts the app actually loads', () => {
  /**
   * The failure this exists for is silent. A `fontFamily` the app never
   * registered does not throw — React Native falls back to the system sans, on
   * every screen, and the design system quietly stops being the design system.
   *
   * That is not hypothetical: the first version of these tokens named a family
   * called "HankenGrotesk" and nothing in the project loaded any font at all.
   * Everything rendered, and none of it was the brand.
   */
  for (const role of Object.values(type)) {
    expect(Object.keys(FONTS)).toContain(role.fontFamily);
  }
});

it('carries the weight in the family name rather than beside it', () => {
  /**
   * Android does not synthesise weights for a custom family: it resolves the
   * registered name and ignores `fontWeight`. A token with both would render
   * correctly on iOS and at regular weight on Android — a bug split down the
   * platform nobody develops on.
   */
  for (const role of Object.values(type)) {
    expect(role).not.toHaveProperty('fontWeight');
  }
});

it('gives every type role a line height with room to breathe', () => {
  for (const role of Object.values(type)) {
    expect(role.lineHeight).toBeGreaterThanOrEqual(role.fontSize * 1.2);
  }
});

it('offers the oversized container radius the brand commits to', () => {
  /** §9 names "28px container radius" as brand truth. */
  expect(radius.container).toBe(28);
});
