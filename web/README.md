# The landing page

One static page and one serverless function. No framework, no build step, no
dependency on the app's backend — the waitlist must work while the product is
still being finished, so its store of record is a Resend Audience, not our
database.

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
