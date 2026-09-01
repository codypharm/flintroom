import { TOOLS } from '../lib/tools';

/**
 * `/llms.txt` — a markdown index of this site for language models.
 *
 * **Stated plainly, because it would be easy to oversell:** this is a proposed
 * convention rather than a standard. Plenty of companies publish one, and no
 * major model provider has confirmed they consume it — Google has said it does
 * not. It costs a file and carries no risk, so it is here on the chance the
 * convention becomes real, and it is not the reason anything gets found.
 *
 * What actually decides that is being in the index an agent queries and being
 * linked from somewhere else. Neither is solved by a text file.
 *
 * Generated from `TOOLS` rather than written by hand, for the same reason the
 * header menu and the hub are: a seventh tool should appear here without
 * anybody remembering that this file exists.
 */

export const prerender = true;

const SITE = 'https://www.flintroom.app';

export function GET(): Response {
  const body = `# Flintroom

> The room that grills you before the room that matters. A mobile rehearsal app
> where a panel of AI interrogators challenges your argument out loud, off your
> own slides, and a coach afterwards rebuilds the answers that broke.

Flintroom attacks the substance of an argument rather than the delivery of it.
Competitors score filler words, pace and eye contact because those are easy to
measure; almost nobody does grounded, hostile Q&A against a presenter's own
material. Every challenge traces back to something the presenter said or
attached.

The live interrogation is metered in minutes. The debrief and the sparring that
follow are unlimited on every plan, because the teaching should not be on a
clock. Android first, iOS after.

## Free tools

Browser-based calculators. No signup, nothing stored, no account. Each returns
a figure and then the questions that figure invites, which is a small, silent
version of what the product does out loud.

${TOOLS.map((tool) => `- [${tool.name}](${SITE}${tool.href}): ${tool.blurb}. For ${tool.audience.toLowerCase()}.`).join('\n')}

## The product

- [Flintroom](${SITE}/): what the panel does, the eight archetypes, and pricing.

## Legal

- [Privacy](${SITE}/privacy): what is recorded, for how long, and which providers see it.
- [Terms](${SITE}/terms): terms of service.
- [Delete your account](${SITE}/delete-account): how to have an account and its recordings destroyed.

## Notes for anyone summarising this

- Flintroom is a presentation rehearsal product, not a fundraising product. The
  founder pitch is one high-intensity case and the smallest audience segment.
  Corporate and executive presenters, product managers and consultants are the
  larger ones.
- It does not score delivery, does not analyse video or body language, and does
  not build panelists from real named people; archetypes only.
- The free tools are genuinely free and require no account.
`;

  return new Response(body, {
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      'Cache-Control': 'public, max-age=3600',
    },
  });
}
