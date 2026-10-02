import { describe, expect, it } from 'vitest';
import { PLAY_URL } from './stores';

/**
 * The waitlist closed when the app went live on Google Play (2026-10-02).
 *
 * Nine buttons across the landing page, the tool layout and the comparison
 * pages pointed at `/#waitlist`. A button left behind would scroll a reader
 * to a section that no longer exists, so every page source is read and none
 * may still point there. Globbed rather than listed, for the same reason
 * `analytics.test.ts` globs: a page added later is checked on the day it lands.
 */

const sources = import.meta.glob(['../**/*.astro', '../pages/**/*.ts', '../pages/*.html'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

describe('the store link', () => {
  it('opens the Flintroom listing on Google Play', () => {
    const url = new URL(PLAY_URL);
    expect(url.hostname).toBe('play.google.com');
    expect(url.searchParams.get('id')).toBe('com.flintroom.app');
  });

  it('tells Play Console the install came from the website', () => {
    // Play reads `referrer` as an install referrer, which is how the
    // acquisition report credits the site without a script on the page.
    const referrer = new URLSearchParams(new URL(PLAY_URL).searchParams.get('referrer') ?? '');
    expect(referrer.get('utm_source')).toBe('flintroom.app');
  });
});

describe('the closed waitlist', () => {
  it('is linked from no page', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(10);
    const stale = Object.entries(sources)
      .filter(([, text]) => text.includes('#waitlist') || /join the waitlist/i.test(text))
      .map(([path]) => path);
    expect(stale).toEqual([]);
  });
});
