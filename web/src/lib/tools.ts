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
}

export const TOOLS: Tool[] = [
  {
    href: '/tools/runway-calculator',
    name: 'Runway calculator',
    blurb: 'The date you run out, with spend and revenue both growing',
    audience: 'Founders',
  },
];
