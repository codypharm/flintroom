import { describe, expect, it } from 'vitest';

/**
 * Every page that owns a `<head>` carries the tag.
 *
 * The site has two kinds of page and only one of them shares a layout. The
 * landing page and the eight tool pages render through `Base.astro`, so a tag
 * added there reaches all nine at once. `privacy`, `terms` and
 * `delete-account` are plain `.html` files with their own head, and a tag
 * added to the layout misses them silently. That is the same trap
 * `astro.config.mjs` already records for the sitemap, which is why the sitemap
 * is hand-written rather than generated.
 *
 * So the static pages are globbed rather than listed. A tenth page dropped
 * into `pages/` as raw HTML fails here on the day it is added, which is the
 * only moment the omission is cheap to fix.
 *
 * Read through Vite's `?raw` rather than `node:fs`, so the web workspace does
 * not acquire `@types/node` for the sake of one test.
 */

const MEASUREMENT_ID = 'G-Q1GZBK57YS';

// The options have to be an inline literal: Vite parses this call at build
// time and refuses a variable.
const staticPages = import.meta.glob('../pages/*.html', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

const layouts = import.meta.glob('../layouts/Base.astro', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

const snippets = import.meta.glob('./Analytics.astro', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

const snippet = Object.values(snippets)[0]!;

describe('the tag reaches every page', () => {
  it('has static pages to check, so an empty glob cannot pass', () => {
    expect(Object.keys(staticPages).length).toBeGreaterThan(0);
  });

  it.each(Object.entries(staticPages))('%s carries the tag itself', (_path, source) => {
    expect(source).toContain(MEASUREMENT_ID);
  });

  it('the layout carries it for every page rendered through it', () => {
    expect(Object.values(layouts)[0]).toContain('<Analytics />');
  });
});

describe('what the tag is allowed to do', () => {
  it('runs only on the canonical host', () => {
    // Vercel builds a preview deployment for every push, and `astro dev`
    // serves these same pages on localhost. Neither is the site, and without
    // this both report into the same property as the real thing.
    expect(snippet).toContain("location.hostname !== 'www.flintroom.app'");
  });

  it('denies storage by default, which is what keeps the banner off', () => {
    // Consent Mode with analytics_storage denied means cookieless pings. No
    // cookie is set, so there is nothing for a consent banner to ask about,
    // and the tool pages can keep promising that nothing is stored.
    expect(snippet).toContain("analytics_storage: 'denied'");
  });

  it('never asks for the advertising storage', () => {
    // Google Signals is off in the property. Nothing here should be
    // requesting the storage that would feed it.
    expect(snippet).toContain("ad_storage: 'denied'");
    expect(snippet).not.toContain("'granted'");
  });

  it('sets consent before configuring, or the default does not apply', () => {
    expect(snippet.indexOf("gtag('consent'")).toBeLessThan(snippet.indexOf("gtag('config'"));
  });

  it('is copied into the static pages unchanged', () => {
    // The copies cannot import the component. If they drift, the promise the
    // privacy page makes stops matching what three of its own pages do.
    const body = snippet.slice(snippet.indexOf('(function ()'), snippet.indexOf('})();'));

    for (const [path, source] of Object.entries(staticPages)) {
      expect(source, path).toContain(body);
    }
  });
});
