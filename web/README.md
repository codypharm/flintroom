# The landing page

An Astro site and one serverless function. Static output, no server adapter,
and no dependency on the app's backend — the waitlist must work while the
product is still being finished, so its store of record is a Resend Audience,
not our database.

## Why there is a build step now

There was not one until #113. The site was four hand-written HTML files, and
that was the right shape while there were four of them.

What changed is #111: a set of free calculators, each its own page, each
needing the same header, footer, tokens and social tags. Seven copies of a nav
is where hand-written HTML stops paying. Astro was chosen over Next.js because
these pages are mostly static with one interactive island, and Next would ship
a React runtime for a page that is a form and some arithmetic.

**Astro was not chosen for SEO.** Hand-written static HTML was already the best
case a crawler can be given; a React SPA is the worst, and Next only reaches
parity by pre-rendering — that is, by producing what this directory already
produced. The framework buys shared layout and generated metadata, nothing
about ranking.

## What is where

```
src/pages/index.astro      the landing page
src/layouts/Base.astro     <head>, social tags, the stylesheet import
src/components/            Header, Footer
src/styles/site.css        the landing page's stylesheet, moved verbatim
src/pages/privacy.html     ┐
src/pages/terms.html       ├ plain HTML routes, content untouched
src/pages/delete-account.html ┘
public/robots.txt          hand-written
public/sitemap.xml         hand-written — see the comment inside it
api/waitlist.js            a plain Vercel function, not an Astro endpoint
```

**The three legal pages stay static on purpose.** They are cited in store
submission material, they change roughly never, and they deliberately carry a
reduced header — brand and one way back, no sections, no call to action.
Putting "Free tools" and "Pricing" on a privacy policy is marketing where
somebody came for a fact.

**`api/waitlist.js` stays a plain Vercel function on purpose.** Either shape
runs as a Vercel serverless function, but a plain file is not downstream of the
Astro build, so a build error cannot take the waitlist down with it.

## Working on it

```
npm install
npm run dev          # local, with hot reload — Astro pages only
npm run preview      # serves the real build — use this to click the whole site
npm run check        # Astro + TypeScript diagnostics
npm run build        # writes dist/
```

**Why the legal pages are `.html` files in `src/pages/` and not in `public/`.**
Astro routes plain HTML files as pages, so `/privacy` resolves in `dev`, in
`preview` and in production, and the file itself is passed through untouched —
the build output is byte-identical to what is live today.

They were in `public/` first, which does not work: Astro's dev server serves
`public/` verbatim with no directory-index resolution, so every footer link
404'd locally while working fine in production. That is the worst shape a bug
can have. Flat `public/privacy.html` had the same problem in a different place
— it resolved only because `vercel.json` sets `cleanUrls`, which made two URLs
handed to store reviewers depend on one checkbox in one vendor's dashboard.

Being routed by Astro changes nothing about them otherwise: no layout, no
header, no components, no shared tokens. A legal page keeps its own reduced
chrome for the reason given above.

CI runs `check` and `build` on every push. Vercel builds and deploys `web/` on
every push, so a build that only fails there fails after the commit is already
the newest thing on the branch.

## Deploy (once)

1. **Resend** (resend.com): create an API key, create an **Audience** named
   `Waitlist`, and note its id. To send from `hello@flintroom.app` instead of
   Resend's test sender, verify the domain under *Domains* (two DNS records);
   until then the fallback sender works for testing.
2. **Vercel**: *New Project* → import this repository → set **Root Directory
   to `web/`** → add environment variables:
   - `RESEND_API_KEY`
   - `RESEND_AUDIENCE_ID`
   - `RESEND_FROM` (optional until the domain is verified, e.g.
     `Flintroom <hello@flintroom.app>`)
3. Deploy. Attach the real domain under *Domains* when ready.

Every push to `web/` redeploys. Prices, copy, and the panel on this page are
marketing surface, not product truth — `Product.md` stays the source of truth
and this page follows it, never the other way round.

## Launch day

The Audience is the broadcast list: Resend → Broadcasts → send to `Waitlist`.
The welcome email already promises exactly one email, so send exactly one.

## What the function does

`api/waitlist.js`: validates the address, drops honeypot submissions with a
fake success (telling a bot it was caught only trains it), adds the contact to
the Audience (a repeat signup reads as success — it is a person
double-checking, not a fault), and sends a welcome email best-effort. No
tracking, no analytics, and the page makes one promise the launch email has to
keep: one email when we open, and nothing else.

## Measurement

Google Search Console, and nothing on the page. `privacy.html` says telemetry
"never goes to an analytics company" and that Flintroom runs no tracking SDKs;
that page is handed to store reviewers, and it does not read as being scoped to
the app only. Search Console is crawler-side, so it breaks no promise and still
answers the questions that matter: is this searched, do we rank, do they click.

Conversion is measured server-side from the waitlist submission rather than
from a script on the page. Anything on-page — including the cookieless
options — needs an honest privacy-policy edit first.
