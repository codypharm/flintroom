# Comparison pages

**Written 2026-09-18.** `web/src/lib/competitors.ts`, `/alternatives`, and the
rules that keep them from becoming a liability.

People search for "yoodli alternative" before they search for us, and the pages
that rank for those queries are written by the competitors of the product being
searched. That is a legitimate and well-worn tactic, and this is our version of
it.

It is also the only place on the site where we state facts about another
company, which is why it has a doc and a test file rather than just a page.

---

## The incident this was designed around

The first draft of the Yoodli page was going to open with the wedge sentence
from `Product.md` §1: competitors score delivery, almost nobody does grounded
hostile Q&A against the user's own content.

Checked against Yoodli's own pages on 2026-09-18, that sentence was roughly a
year out of date. They advertise uploading a deck or document, an AI that
presents the slides and explains "material grounded in the uploaded files",
"AI-powered follow-up questions", and simulating "a group presentation, buying
committee pitch or interview panel".

So the page would have led with a checkably false claim about the best-funded
product in the category, on a page whose most motivated reader is that company.
Nothing caught it except going and reading their site, which is now the rule.

**What survived the check is narrower and better.** Their pages describe an AI
that teaches you *from* your material. Flintroom cross-checks what you say out
loud *against* it and interrupts when the two disagree. That is the Auditor, and
it is a claim someone can verify by opening both products.

## The rules

Enforced by `web/src/lib/competitors.test.ts`, which is most of what that file
is for. Almost none of it tests rendering.

1. **Every claim carries a URL on their own site and the date it was read.** Not
   a review site, not a roundup, not a model's recollection. Their own page is
   the only source that cannot be answered with "that is not what we say".
2. **No claim may say a competitor "cannot" do something.** We can read a page.
   We cannot read a release we have not been shown. The permitted form is that
   their page does not claim it, which is true and checkable. The test greps for
   `cannot`, `does not support`, `lacks` and friends.
3. **Every competitor gets at least two genuine strengths**, and the page prints
   them *before* the difference. A reader who has used the other product stops
   reading at the first thing they know to be false, and everything after that
   is wasted. Conceding first is not manners, it is what gets the second half
   read.
4. **Every page says plainly who should pick the other one.** If that section is
   hard to write honestly, the comparison probably should not ship.
5. **No sneering.** The test greps for `useless`, `clunky`, `overpriced` and the
   rest. Hostility is the product, not the marketing.
6. **Brand voice applies.** No em dashes, no exclamation marks, both tested.
7. **Claims go stale after a year and the test fails.** A deliberate time bomb,
   the same judgement `api/waitlist.test.js` makes. If it fires, re-read the
   cited pages and move the dates. Do not widen the window.

Two rules no test can reach:

- **Never use a competitor's logo.** Their name in text and in the page title is
  nominative fair use. Their mark is a separate risk for no benefit.
- **Never publish a table where we win every row.** It is the format readers
  have already learned to distrust, and it is the one we could least defend:
  Flintroom has no users, no benchmarks and nothing measured.

## Decisions

**`/alternatives/<slug>`, with a hub at `/alternatives`.** The hub is the page
that collects the internal links and ranks for the category rather than for one
product name, exactly as `/tools` does. Google stopped rewarding keyword-stuffed
root paths long ago, and a flat `/yoodli-alternative` would put competitor names
in our root namespace forever.

**The closing block says the product is not open yet.** Someone searching for an
alternative wants something to use today, and sending them to a "Get started"
button that turns out to be a waitlist would make the honesty of the rest of the
page worthless. The pages ship before launch anyway, because ranking takes
months and an unindexed page ranks for nothing.

**A separate `Compare.astro` layout rather than a flag on `Tool.astro`.** Same
furniture, different register, different breadcrumbs and siblings. Threading two
registers through one layout would make both harder to read.

## Adding one

1. Read their pages. All of them: homepage, pricing, the feature announcements.
   Do not start from what you remember about the product.
2. Add an entry to `COMPETITORS` in `web/src/lib/competitors.ts`. Ordered by how
   many people are looking for each one.
3. `npm test` in `web/`. The rules above are the test.
4. The hub, the sitemap, `llms.txt` and the sibling links all read from the
   register, so there is nothing else to update. That is the point of it (#119).

**A human reads the claims before they ship.** An agent can fetch a page and
quote it, and an agent is also exactly what would confidently restate a stale
positioning line. The register is where a wrong sentence becomes a published
one, so it does not merge unread.
