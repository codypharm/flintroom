# Brand and voice

**Written 2026-09-18. For anything that speaks outward: social posts, the
landing page, store listings, ads, a deck about the product.**

This is the brief to paste into a content tool that asks for "brand guidelines,
voice, style, visuals". It is self-contained on purpose, so it can be handed to
something that cannot read the rest of this repository.

**It is not `design-guide/`.** That folder is the app's UI design system, and its
eight screen mockups are stale: they predate two renames and encode a token
counter, an "investment verdict" screen and an "Avg. Likelihood %" that no
longer exist (`Product.md` §9). Its hero images are unlicensed AI stock hosted
on Google's CDN and must never be published. Only the tokens carry forward, and
the ones that matter outward are repeated below.

Everything here traces to `Product.md` §1, §2 and §9, to `CLAUDE.md`, or to
`app/src/theme/tokens.ts`. When one of those changes, change this.

---

## The product, in one paragraph

Flintroom is a mobile, hands-free rehearsal app for high-stakes speaking. A
panel of AI archetypes interrogates your argument out loud, challenges your
numbers, and catches contradictions between what you say and what your deck
claims. Afterwards a coach walks you through what held and what came loose, and
you answer the weak questions again until they stand up.

The premise, which is the line most copy should be built from: **the thing people
dread is not presenting. It is being asked a question they cannot answer, in
front of people who matter.**

## Name and tagline

- **Flintroom.** One word, capital F, never "FlintRoom" or "Flint Room".
- **Tagline: "The room that grills you before the room that matters."** Confirmed
  and not to be paraphrased in a headline. Shorter variants are fine as body
  copy, not as the tagline.

## Positioning

**What it is:** an adversarial simulator plus a coach. Pressure first, teaching
second.

**What it is not:** a recording utility, a delivery-metrics scorer, or a slide
generator.

**The wedge, which every post should protect.** Yoodli, Orai, VirtualSpeech,
Ovation and Microsoft Speaker Coach all score *delivery*: filler words, pace, eye
contact. They do that because delivery is easy to measure. Almost nobody does
grounded, hostile Q&A against the user's own material. That is the gap Flintroom
sits in. A post that says "get feedback on your presentation" describes the
saturated category and sells nothing.

The strongest single contrast, usable almost anywhere:

> Most speaking apps count your filler words. Flintroom checks your numbers.

## Who it is for

Corporate and executive presenters (board reviews, exec readouts, QBRs),
product managers defending a roadmap or a headcount request, consultants and
agency leads on a client defense, and startup founders. Students and academics
facing a viva or conference Q&A are secondary.

**Lead with the situation, not the job title.** "You are about to be grilled"
travels across all of those. "Pitch practice for founders" caps the audience at
the smallest segment and tells a corporate reader it is not for them. Founders
are one case, not the definition.

**Never** position it for social or dating practice. That is a different buyer
and a different category, and it is explicitly out of scope.

## Voice

Direct and unsentimental, the way a good coach speaks after a hard session.
Never cruel, never gamified-cheerful.

The tone problem to solve: being attacked is already uncomfortable. Copy's job
is to make the discomfort feel deliberate and worth it, rather than softening it
into encouragement or amplifying it into humiliation.

**Do**

- Short sentences. Concrete nouns. The specific situation over the abstract
  benefit: "the board member who asks where the 40% came from", not "challenging
  questions".
- Name the fear plainly, then name what the product does about it.
- Let the product's own behaviour carry the claim. A panelist catching a
  contradiction is more persuasive than any adjective.

**Don't**

- No hype punctuation: no exclamation marks, no all-caps, no rocket or fire
  emoji. One emoji at most in a post, and only where a platform makes text
  without one look broken.
- No cruelty as a hook: not "your pitch is terrible", not "get destroyed".
  Hostility is the product; humiliation is the churn.
- No motivational filler: "crush it", "level up", "unlock your potential".
- **No em dashes in outward copy.** Use a comma, a colon or a full stop. This
  holds for every user-facing surface.
- No fake scarcity, countdowns, or "only 3 spots left".

**A line that works, and the same idea failing**

> Good: "You rehearse the answer you have. The room asks the question you don't."
>
> Bad: "Practice makes perfect! Flintroom helps you become a confident speaker."

## Vocabulary

Use these exactly. They are the product's words and they keep everything
searchable and consistent.

| Term | Means |
| --- | --- |
| **Panel** | The set of AI archetypes interrogating you |
| **Archetype** | A pre-built panelist persona, never a real person |
| **Interrogation** | The live, hands-free Q&A phase |
| **Debrief** | The coach walkthrough afterwards |
| **Sparring** | Re-answering a fumbled question until it holds |
| **Room temperature** | The live read on how the panel is receiving you |
| **Minutes** | The unit of interrogation time |

The shipped archetypes are **The CFO, The Technical Skeptic, The Champion, The
Growth Maximalist, The Distracted Executive, The Internal Blocker, The Customer
Advocate, The Risk Officer.** Do not invent a ninth for a post.

**Words we do not use:** "AI-powered" as a headline claim, "revolutionary",
"game-changer", "seamless", "effortless" (the product is deliberately not
effortless), "pitch deck coach", "public speaking anxiety cure".

## Visual identity

The design tokens are brand truth and carry forward under the Flintroom name.
The aesthetic is warm professionalism: airy, tactile, paper-on-surface. Modern
minimalism with warmth, deliberately not the cold blue-grey of corporate SaaS.

**Colour**

| Role | Hex | Use |
| --- | --- | --- |
| Primary, burnt orange | `#a43700` | The brand colour. Buttons, accents, one highlighted word |
| Primary container | `#cd4700` | A brighter orange for larger fills |
| Surface, warm off-white | `#f0e9e5` | The canvas for anything light |
| Card | `#ffffff` | Sheets sitting on the canvas |
| Text, dark charcoal | `#1c1b1b` | Headlines and body |
| Text, warm grey | `#5a4138` | Secondary lines |

The interrogation is the one dark surface, and it is the most photogenic thing
the product has: a near-black warm ground, `#15110f`, with light text at
`#f3f0ef` and active elements in `#ffb59a`. It is a darkroom under a safelight,
not a generic dark mode. Use it for anything showing the live room. Everything
else, setup and debrief and library, is light.

Do not introduce a second palette. Do not use blue, purple or a gradient mesh.

**Type.** Hanken Grotesk throughout. Headlines heavy (600 to 700) with tight
letter spacing, around -0.02em. Body at 400 with generous line height, 24 to
28px. It is on Google Fonts, so a content tool can use it directly.

**Shape and depth.** 28px corner radius on cards and containers. Buttons and
inputs are full pills. Depth comes from soft ambient shadow, never a hard border:
`0 8px 24px -4px rgba(26,26,26,0.04)`. Spacing is a strict 4px baseline, 24px
inside a card.

**Imagery.** A phone lying flat on a desk is the product's true image, because
the live phase is hands-free and eyes-up. Meeting rooms, boardroom tables,
someone mid-sentence in front of people. Avoid the stock-photo register:
handshakes, laptops on beaches, headset call-centre smiles, and any depiction of
the AI as a robot, an orb or a glowing brain. The panel is people-shaped in
imagination and abstract on screen.

**Motion**, where a platform allows it: calm and weighted. Nothing bounces.

## Hard rules for anything published

These are compliance rules, not preferences. Each has a reason behind it.

- **No prices, tier names or minute counts.** Every price in the spec is an
  unverified assumption until cost reconciliation closes. The one safe money
  claim is that coaching never uses your minutes, which is true by design.
- **No users, sessions, testimonials, case studies, customer logos, accelerator
  badges, ratings, download counts, latency figures or retention data.** None of
  it exists yet. Do not fabricate it, and do not imply it with phrases like
  "join thousands".
- **No real person's name, likeness, voice or company on a panel.** Panelists are
  archetypes. This is a legal line, not a style one.
- **Never describe Flintroom as scoring delivery:** pace, filler words, eye
  contact, posture, confidence level. That is the competitor product.
- **No retired framing:** "Investable", "Delusional", likelihood percentages,
  token counters, or anything calling the product pitch-only.
- **Nothing readable as a guarantee.** Not "you'll win the room", not "get
  funded", not "never get stumped again". Store reviewers read these.
- **No claims about recording, storage or privacy** beyond what
  `docs/privacy-policy.md` says. If a post needs to touch it, check there first.
- **No logo or wordmark exists.** Do not generate one, do not place one, do not
  imply one exists. Set the name in Hanken Grotesk until a real mark is made.

## Things that are true and usable

A short list of claims that are safe because the code does them:

- The panel quotes figures from the deck you attached.
- It is hands-free. The phone sits on the desk.
- Captions follow every panelist, live.
- Coaching and re-tries are unlimited and never spend your minutes.
- Every room is saved, and you can run the same argument again and watch it get
  stronger.
- The panel is mixed by default: a skeptic, a champion, someone neutral.
