// @ts-check
import { defineConfig } from 'astro/config';

/**
 * Static output, no adapter, deployed exactly as before.
 *
 * `web/api/waitlist.js` stays a plain Vercel function at the project root
 * rather than becoming an Astro endpoint (#113 decision 3). Both shapes run
 * as a Vercel serverless function — same runtime, same billing — but the
 * plain file is not downstream of this build, so an Astro error cannot take
 * the waitlist down with it. That is also what keeps `README.md`'s claim
 * literally true: the marketing site does not depend on our backend, and now
 * it does not depend on our frontend build either.
 *
 * `site` is here for canonical URLs and for `@astrojs/sitemap` when it
 * eventually earns its place. Today the sitemap is hand-written in
 * `public/`, because the integration only knows about Astro's own pages and
 * would silently omit the three store-cited legal pages that live as static
 * files — an incomplete sitemap is worse than none.
 */
export default defineConfig({
  site: 'https://www.flintroom.app',
});
