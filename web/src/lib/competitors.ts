/**
 * The comparison pages, in one register.
 *
 * Same shape as `TOOLS`, and for the same reason: the hub, the sitemap,
 * `llms.txt` and the sibling links all read from here, so a new page cannot be
 * findable everywhere except the sitemap (#119).
 *
 * **Why every sentence carries a URL and a date.** These are the only pages on
 * the site that state facts about another company. Comparative claims are
 * lawful; false ones are actionable, and the reader most likely to check is the
 * company being described. `competitors.test.ts` enforces the rules; this
 * comment is why they exist.
 *
 * The cost of getting it wrong was demonstrated before a line shipped. On
 * 2026-09-18 the wedge in `Product.md` §1 ("almost nobody does grounded,
 * hostile Q&A against the user's own content") was checked against Yoodli's own
 * pages and found a year out of date: they advertise deck upload, an AI that
 * presents and explains the material, follow-up questions, and simulating an
 * interview panel. The first draft of this page would have published that
 * sentence under our name.
 *
 * What survived the check is narrower and better: their pages describe an AI
 * that teaches you **from** your material. Ours cross-examines you **against**
 * it. See `docs/competitor-pages.md`.
 */

export interface Claim {
  /**
   * One sentence, in our words, faithful to theirs. Quote their phrasing where
   * the exact words matter.
   *
   * It may say what their page claims, or that their page does not claim
   * something. It may never say a product "cannot" do a thing: we can read a
   * page, we cannot read a release we have not been shown.
   */
  says: string;
  /** The page on their own site that this was read from. */
  source: string;
  /** ISO date it was last read. Shown on the page, so staleness is visible. */
  checked: string;
}

export interface Competitor {
  slug: string;
  /** Their product name, spelled the way they spell it. */
  name: string;
  site: string;
  /** The <title>, shaped like the query somebody types. */
  title: string;
  description: string;
  /** For the reader who wants to decide in one sentence and leave. */
  shortAnswer: string;
  /** What they do well. At least two, and meant sincerely. */
  strengths: Claim[];
  /** Where Flintroom differs, each anchored to what their page does claim. */
  differences: Claim[];
  pickThemIf: string;
  pickUsIf: string;
}

/** Ordered by how many people are looking for each one. */
export const COMPETITORS: Competitor[] = [
  {
    slug: 'yoodli',
    name: 'Yoodli',
    site: 'https://yoodli.ai',
    title: 'A Yoodli alternative for presentation Q&A',
    description:
      'What Yoodli does well, where Flintroom differs, and which one fits the room you are walking into. Every claim cited from Yoodli’s own pages, with the date it was read.',
    shortAnswer:
      'Yoodli is a well-funded roleplay platform built for sales and enablement teams, and it is good at that. Flintroom does one narrower thing: it cross-examines you against the deck you attached.',
    strengths: [
      {
        says: 'Yoodli gives "real-time feedback on your content, delivery, and progress over time", including pacing, conciseness and sentence starters.',
        source: 'https://yoodli.ai/',
        checked: '2026-09-18',
      },
      {
        says: 'It runs live AI roleplays and can "Simulate a group presentation, buying committee pitch or interview panel", with AI-powered follow-up questions.',
        source: 'https://yoodli.ai/',
        checked: '2026-09-18',
      },
      {
        says: 'You can upload a deck or document, and the AI will present the slides on its own screen and explain "material grounded in the uploaded files".',
        source:
          'https://yoodli.ai/feature-announcements/introducing-ai-roleplays-with-live-visual-content-learn-and-practice-in-one-continuous-experience',
        checked: '2026-09-18',
      },
      {
        says: 'It is built to be rolled out across a team, with dashboards, SSO, SCIM and admin controls on the team and enterprise plans.',
        source: 'https://yoodli.ai/pricing',
        checked: '2026-09-18',
      },
      {
        says: 'Individual plans are priced at $8 a month for Pro and $20 a month for Advanced, both billed annually, with a free tier of five lifetime sessions.',
        source: 'https://yoodli.ai/pricing',
        checked: '2026-09-18',
      },
    ],
    differences: [
      {
        says: 'Yoodli’s page describes the AI presenting your material, explaining it, and adapting to your questions about it. It does not claim to compare what you say out loud against the document and flag where the two disagree, which is the one thing Flintroom is built to do.',
        source:
          'https://yoodli.ai/feature-announcements/introducing-ai-roleplays-with-live-visual-content-learn-and-practice-in-one-continuous-experience',
        checked: '2026-09-18',
      },
      {
        says: 'Yoodli positions itself around revenue teams, learning and development, and always-on training programmes. Flintroom is for one person with one argument to defend, and the panel is a room rather than a curriculum.',
        source: 'https://yoodli.ai/',
        checked: '2026-09-18',
      },
    ],
    pickThemIf:
      'You want a broad communication coach, feedback on live calls, or roleplay training you can roll out across a sales or enablement team.',
    pickUsIf:
      'You have a deck with numbers in it, and the part you are dreading is the questions those numbers invite.',
  },
];

export const hrefFor = (competitor: Competitor): string => `/alternatives/${competitor.slug}`;
