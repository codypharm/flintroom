import { TOOLS } from '../lib/tools';

/**
 * `/sitemap.xml` — generated from the register, not written by hand.
 *
 * It was a static file in `public/`, and the seventh tool proved why that
 * fails: the page shipped, the header and hub and llms.txt all picked it up
 * from `TOOLS`, and the sitemap — the one file search engines actually poll —
 * silently did not (#119). Now the register is the source here too, and a
 * new tool cannot be findable everywhere except the place that matters.
 *
 * No `lastmod`. It was never true — the static file stamped every URL with
 * the day it was written — and a wrong lastmod is worse than none, because
 * crawlers that trust it skip pages that changed.
 */

export const prerender = true;

const SITE = 'https://www.flintroom.app';

const PAGES = [
  '/',
  '/tools',
  ...TOOLS.map((tool) => tool.href),
  '/privacy',
  '/terms',
  '/delete-account',
];

export function GET() {
  const body = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ...PAGES.map((page) => `  <url><loc>${SITE}${page === '/' ? '' : page}</loc></url>`),
    '</urlset>',
    '',
  ].join('\n');

  return new Response(body, {
    headers: { 'Content-Type': 'application/xml; charset=utf-8' },
  });
}
