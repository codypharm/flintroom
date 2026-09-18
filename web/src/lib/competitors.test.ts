import { describe, expect, it } from 'vitest';

import { COMPETITORS, hrefFor, type Claim } from './competitors';

/**
 * The rules a comparison page has to keep.
 *
 * These pages are the only thing on the site that states facts about another
 * company. A wrong one is not a typo: comparative advertising is lawful and
 * false statements of fact about a competitor are actionable, and the reader
 * most likely to check is the company being described.
 *
 * So almost nothing here tests rendering. It tests that every claim can be
 * traced to a page on a date, that no claim asserts an absence we cannot see,
 * and that we concede something. The failure mode is not an ugly page, it is a
 * confident sentence nobody can back up.
 *
 * The premise this whole directory exists to prevent: on 2026-09-18 the wedge
 * sentence in `Product.md` §1 was found to be a year out of date, and the first
 * draft of the Yoodli page would have published it.
 */

const everyClaim = (): Array<{ competitor: string; claim: Claim }> =>
  COMPETITORS.flatMap((competitor) =>
    [...competitor.strengths, ...competitor.differences].map((claim) => ({
      competitor: competitor.name,
      claim,
    })),
  );

describe('every claim is traceable', () => {
  it('cites a page on their own site', () => {
    // Not a review site, not a roundup, not a model's recollection. Their own
    // page is the only source that cannot be answered with "that is not what
    // we say" — and it is the one a reader can open in a second tab.
    for (const { competitor, claim } of everyClaim()) {
      expect(claim.source, `${competitor}: ${claim.says}`).toMatch(/^https:\/\//);
    }
  });

  it('records the day it was read', () => {
    for (const { competitor, claim } of everyClaim()) {
      expect(claim.checked, `${competitor}: ${claim.says}`).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(Number.isNaN(Date.parse(claim.checked))).toBe(false);
    }
  });

  it('was not read in the future', () => {
    const today = new Date();
    for (const { competitor, claim } of everyClaim()) {
      expect(Date.parse(claim.checked), `${competitor}: ${claim.says}`).toBeLessThanOrEqual(
        today.getTime(),
      );
    }
  });

  it('is not a year stale', () => {
    // A deliberate time bomb, and the same judgement `api/waitlist.test.js`
    // makes: some failures are only catchable by a check that refuses to age
    // quietly. These products ship constantly. If this fails, re-read the
    // cited pages and move the dates; do not widen the window.
    const yearMs = 365 * 24 * 60 * 60 * 1000;
    const cutoff = Date.now() - yearMs;
    for (const { competitor, claim } of everyClaim()) {
      expect(
        Date.parse(claim.checked),
        `${competitor}: "${claim.says}" was last checked on ${claim.checked}. Re-read ${claim.source}.`,
      ).toBeGreaterThan(cutoff);
    }
  });
});

describe('what a claim may assert', () => {
  it('never says a competitor cannot do something', () => {
    // We can see what a page claims. We cannot see what a product does in a
    // release we have not been shown, and "X cannot do Y" is the sentence most
    // likely to be both false and quotable. The permitted form is that their
    // page does not claim it.
    const asserts = /\b(cannot|can't|does not support|doesn't support|is unable|has no (?:way|ability)|lacks)\b/i;

    for (const { competitor, claim } of everyClaim()) {
      expect(asserts.test(claim.says), `${competitor}: ${claim.says}`).toBe(false);
    }
  });

  it('never grades or sneers', () => {
    const sneers = /\b(terrible|useless|garbage|rip[- ]?off|overpriced|clunky|outdated|inferior|just a)\b/i;

    for (const { competitor, claim } of everyClaim()) {
      expect(sneers.test(claim.says), `${competitor}: ${claim.says}`).toBe(false);
    }
  });
});

describe('every page concedes something', () => {
  it('credits each competitor with at least two strengths', () => {
    // The all-green table is the format readers have learned to distrust, and
    // it is the one we could least defend: Flintroom has no users and nothing
    // measured. Conceding is what makes the remaining claim believable.
    for (const competitor of COMPETITORS) {
      expect(competitor.strengths.length, competitor.name).toBeGreaterThanOrEqual(2);
    }
  });

  it('says plainly who should pick them instead', () => {
    for (const competitor of COMPETITORS) {
      expect(competitor.pickThemIf.trim().length, competitor.name).toBeGreaterThan(20);
    }
  });
});

describe('the copy follows the brand voice', () => {
  const prose = (): Array<{ where: string; text: string }> =>
    COMPETITORS.flatMap((c) => [
      { where: `${c.name} shortAnswer`, text: c.shortAnswer },
      { where: `${c.name} pickThemIf`, text: c.pickThemIf },
      { where: `${c.name} pickUsIf`, text: c.pickUsIf },
      { where: `${c.name} description`, text: c.description },
      ...[...c.strengths, ...c.differences].map((claim) => ({
        where: `${c.name} claim`,
        text: claim.says,
      })),
    ]);

  it('uses no em dashes', () => {
    // `docs/brand-voice.md`: outward copy takes a comma, a colon or a full stop.
    for (const { where, text } of prose()) {
      expect(text.includes('—'), `${where}: ${text}`).toBe(false);
    }
  });

  it('uses no exclamation marks', () => {
    for (const { where, text } of prose()) {
      expect(text.includes('!'), `${where}: ${text}`).toBe(false);
    }
  });
});

describe('the register', () => {
  it('gives every competitor a unique slug', () => {
    const slugs = COMPETITORS.map((c) => c.slug);
    expect(new Set(slugs).size).toBe(slugs.length);
  });

  it('slugs are lowercase and hyphenated', () => {
    for (const competitor of COMPETITORS) {
      expect(competitor.slug).toMatch(/^[a-z0-9]+(?:-[a-z0-9]+)*$/);
    }
  });

  it('builds the href from the slug', () => {
    // The sitemap, the hub and the sibling links all read this, for the reason
    // #119 gave: a page findable everywhere except the sitemap is not findable.
    for (const competitor of COMPETITORS) {
      expect(hrefFor(competitor)).toBe(`/alternatives/${competitor.slug}`);
    }
  });

  it('links to their real site', () => {
    for (const competitor of COMPETITORS) {
      expect(competitor.site, competitor.name).toMatch(/^https:\/\//);
    }
  });
});
