/**
 * The free tools, in one list.
 *
 * The header menu, the `/tools` hub and the sideways links at the foot of each
 * tool all read from here, so a new page is added in one place rather than
 * three — which is most of why `web/` has a build step at all (#110).
 *
 * `blurb` is what the tool does, not what it is called again. It appears in the
 * menu and on the hub, where a reader is deciding which one they want.
 */

export interface Tool {
  href: string;
  name: string;
  blurb: string;
  /** Who types the query this page answers. Used on the hub, not in the menu. */
  audience: string;
  /**
   * The inner markup of a 24x24 icon, drawn to the same stroke and weight as
   * the rest of the set — `.icon` supplies the geometry, the fill and the
   * 1.8 stroke. Authored rather than borrowed: an emoji standing in for an
   * icon is the one substitution a drawn set can never absorb.
   *
   * Each one says what the tool does rather than what it is about. A falling
   * line for money running out; a circle being divided for a stake being
   * split.
   */
  icon: string;
}

export const TOOLS: Tool[] = [
  {
    href: '/tools/ltv-cac-calculator',
    name: 'LTV:CAC and payback',
    blurb: 'The ratio, the months to pay it back, and the lifetime it assumes',
    audience: 'Founders and operators',
    icon: '<path d="M12 3a9 9 0 1 0 9 9"/><path d="M12 12 21 3"/><path d="M12 12v9"/>',
  },
  {
    href: '/tools/roi-calculator',
    name: 'Business case ROI',
    blurb: 'Payback, NPV, and the share of the benefit that actually has to land',
    audience: 'Executives',
    icon: '<path d="M3 5v13a1 1 0 0 0 1 1h16"/><path d="m7 15 4-5 3 2 5-6"/><path d="M15 6h4v4"/>',
  },
  {
    href: '/tools/dilution-calculator',
    name: 'Dilution calculator',
    blurb: 'SAFEs, the option pool shuffle, and where the points actually went',
    audience: 'Founders',
    icon: '<circle cx="12" cy="12" r="9"/><path d="M12 3v9h9"/><path d="M12 12 5.6 18.4"/>',
  },
  {
    href: '/tools/runway-calculator',
    name: 'Runway calculator',
    blurb: 'The date you run out, with spend and revenue both growing',
    audience: 'Founders',
    icon: '<path d="M3 5v13a1 1 0 0 0 1 1h16"/><path d="m6 8 4 4 3.5-1L19 17"/>',
  },
];
