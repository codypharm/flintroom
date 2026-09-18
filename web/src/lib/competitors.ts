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
  {
    slug: 'orai',
    name: 'Orai',
    site: 'https://orai.com',
    title: 'An Orai alternative for presentation Q&A',
    description:
      'What Orai does well, where Flintroom differs, and which one fits what you are rehearsing. Every claim cited from Orai’s own pages, with the date it was read.',
    shortAnswer:
      'Orai is a mature mobile speaking coach that scores how you sound. Flintroom is not a second opinion on your delivery: it argues with what you said.',
    strengths: [
      {
        says: 'Orai gives instant feedback on filler words, pace, clarity, energy, confidence and conciseness, and it is genuinely good at that measurement.',
        source: 'https://play.google.com/store/apps/details?id=com.orai',
        checked: '2026-09-18',
      },
      {
        says: 'It is the established mobile app in this category, on iOS and Android since 2017, past 100,000 downloads on Google Play and still shipping updates this month.',
        source: 'https://play.google.com/store/apps/details?id=com.orai',
        checked: '2026-09-18',
      },
      {
        says: 'It is cheap and easy to start: $12 a month on their pricing page, an annual plan at $49.99, a one-time lifetime option, and a seven-day free trial.',
        source: 'https://orai.com/pricing/',
        checked: '2026-09-18',
      },
      {
        says: 'It also publishes fifteen free browser tools that need no signup, and a structured four-week programme called Orai Journey.',
        source: 'https://orai.com/tools/',
        checked: '2026-09-18',
      },
    ],
    differences: [
      {
        says: 'Orai describes itself as repeatable speech practice with measurable delivery feedback, and its own comparison pages assign interactive AI roleplays to other products rather than to itself. Nothing on its pages describes an AI that asks you questions and responds to the answer.',
        source: 'https://orai.com/alternatives/yoodli/',
        checked: '2026-09-18',
      },
      {
        says: 'Every metric Orai advertises is a property of how you speak rather than of what you claimed. Its published materials do not describe checking a statement against source material.',
        source: 'https://orai.com/product/',
        checked: '2026-09-18',
      },
      {
        says: 'Orai’s enterprise page does offer loading your own pitch decks and objection scripts for a team to practice with. It describes them as practice scenarios, and does not describe the product reading a deck or comparing what you say against it.',
        source: 'https://orai.com/enterprise/',
        checked: '2026-09-18',
      },
    ],
    pickThemIf:
      'You want to stop saying "um", steady your pace, and build the habit on your phone. Orai has done that for years and does it well.',
    pickUsIf:
      'Your delivery is already fine and the thing that worries you is the question after the slide.',
  },
  {
    slug: 'virtualspeech',
    name: 'VirtualSpeech',
    site: 'https://virtualspeech.com',
    title: 'A VirtualSpeech alternative for presentation Q&A',
    description:
      'VirtualSpeech runs AI panels that push back, including an investor panel. Here is what it does well, where Flintroom differs, and which to pick. Every claim cited and dated.',
    shortAnswer:
      'VirtualSpeech is the closest thing to Flintroom that exists today, and it is a serious enterprise platform with ten years behind it. The honest difference is narrow: their panel questions you on what you said, ours also checks it against the deck you attached.',
    strengths: [
      {
        says: 'VirtualSpeech runs multi-avatar roleplays where several AI characters push back at once, including a Shark Tank style scenario with three investors ready to "test your vision, scrutinize your numbers, and push your strategy to the limit".',
        source: 'https://virtualspeech.com/practice/shark-tank',
        checked: '2026-09-18',
      },
      {
        says: 'Its audience questions are grounded in your actual speech: "AI will understand what you are saying, so the questions are relevant to the content of your speech".',
        source: 'https://virtualspeech.com/practice/answering-questions',
        checked: '2026-09-18',
      },
      {
        says: 'You can add your slides and notes to practice with, and for interviews it builds the session from an uploaded CV and job description.',
        source: 'https://virtualspeech.com/practice/presentation-skills',
        checked: '2026-09-18',
      },
      {
        says: 'Its AI coach is a two-way conversation rather than a scorecard, and it ends with a written plan for the real conversation that you can download.',
        source: 'https://virtualspeech.com/ai-coach',
        checked: '2026-09-18',
      },
      {
        says: 'It runs in a browser with no headset required, has ten years of courses and scenarios behind it, and is built to roll out across an organisation with SSO, LMS integration and analytics.',
        source: 'https://virtualspeech.com/pricing',
        checked: '2026-09-18',
      },
    ],
    differences: [
      {
        says: 'Their questions come from the transcript of what you said. Nothing on their site describes comparing your spoken claim against the document you uploaded and flagging where the two disagree, which is the specific thing Flintroom is built to do.',
        source: 'https://virtualspeech.com/practice/answering-questions',
        checked: '2026-09-18',
      },
      {
        says: 'Slides are described as material to practice with, displayed in the scenario. Their pages do not describe the slides being read, parsed, or used to check what you say.',
        source: 'https://virtualspeech.com/practice/presentation-skills',
        checked: '2026-09-18',
      },
      {
        says: 'VirtualSpeech runs in a browser on a laptop or tablet, or on a VR headset. No phone app is listed on their site. Flintroom is built for a phone lying flat on a desk, hands-free, which is how people actually rehearse.',
        source: 'https://virtualspeech.com/exercises',
        checked: '2026-09-18',
      },
      {
        says: 'It is sold to organisations first, with "Book a demo" as the main route in and individual access listed at $45 a month. Flintroom is for one person with one argument, bought like an app.',
        source: 'https://virtualspeech.com/pricing',
        checked: '2026-09-18',
      },
    ],
    pickThemIf:
      'You are an L&D or education team rolling out communication practice across a lot of people, you want VR, or you need interviews, negotiation and difficult conversations covered as well.',
    pickUsIf:
      'You are one person with a deck, and what you need is the thing that notices your slide says 28% while you just said 40%.',
  },
  {
    slug: 'ovation',
    name: 'Ovation',
    site: 'https://www.ovationvr.com',
    title: 'An Ovation alternative for presentation Q&A',
    description:
      'Ovation puts AI avatars in a room with you and lets you set how hard they push. Here is what it does well, where Flintroom differs, and which to pick. Every claim cited and dated.',
    shortAnswer:
      'Ovation is a desktop and VR rehearsal room with AI avatars that ask real follow-up questions and push back as hard as you tell them to. It judges what you said from the transcript. Flintroom judges it against your deck.',
    strengths: [
      {
        says: 'Its avatars "can listen, react, ask follow-up questions, challenge your ideas", and you set their mood, tone and level of pushback before you start.',
        source: 'https://www.ovationvr.com/faq',
        checked: '2026-09-18',
      },
      {
        says: 'You can seat several at once to simulate investor panels, mock interviews or thesis defences, and the questions follow from what you just said.',
        source: 'https://www.ovationvr.com/individuals',
        checked: '2026-09-18',
      },
      {
        says: 'It imports PowerPoint, PDF and Word files onto virtual screens, notecards and teleprompters, and its interview scenario builds questions from an uploaded resume and job description.',
        source: 'https://docs.ovationvr.com/ovation/speech-items',
        checked: '2026-09-18',
      },
      {
        says: 'Its AI coach goes past delivery, advising on "how well you supported the conclusions in your speech", with more than thirty scoring factors including persuasiveness, structure and clarity.',
        source: 'https://docs.ovationvr.com/ovation/artificial-intelligence',
        checked: '2026-09-18',
      },
      {
        says: 'The individual plan is listed at $15 a month billed annually with a seven-day trial, which is the cheapest serious option in this comparison.',
        source: 'https://www.ovationvr.com/pricing',
        checked: '2026-09-18',
      },
    ],
    differences: [
      {
        says: 'Ovation states its own boundary: the feedback model is given "the speaker’s words and analytics", and its authoring guidance says Ovation "evaluates only the spoken words (transcript)". An imported deck is converted to images for display, so the panel questions what you said rather than what your slide says.',
        source: 'https://docs.ovationvr.com/ovation/artificial-intelligence',
        checked: '2026-09-18',
      },
      {
        says: 'Practice runs in an installed Windows or Mac application, or on a Meta Quest headset. No phone app is listed on their site. Flintroom runs on the phone already on your desk.',
        source: 'https://www.ovationvr.com/faq',
        checked: '2026-09-18',
      },
      {
        says: 'Ovation sells mainly to universities and institutional training programmes, organised by academic department. Flintroom is for one person with one argument to defend.',
        source: 'https://www.ovationvr.com/education',
        checked: '2026-09-18',
      },
    ],
    pickThemIf:
      'You want VR, you are running a course or a cohort, or you want to script the persona yourself and decide exactly how hostile the room is.',
    pickUsIf:
      'You want the room to find the hostile question by itself, out of the deck you attached, rather than you writing the prompt that asks it.',
  },
  {
    slug: 'microsoft-speaker-coach',
    name: 'Microsoft Speaker Coach',
    site: 'https://support.microsoft.com/en-us/office/rehearse-your-slide-show-with-speaker-coach-cd7fc941-5c3b-498c-a225-83ef3f64f07b',
    title: 'A Microsoft Speaker Coach alternative for presentation Q&A',
    description:
      'Speaker Coach is free inside PowerPoint and good at delivery. It reads your slides, but only to catch you reading them aloud. Every claim cited from Microsoft’s own documentation, dated.',
    shortAnswer:
      'Speaker Coach is free, it is already inside the deck, and it is good at what it does. It does look at your slide text, for one purpose: telling you when you are reading it out.',
    strengths: [
      {
        says: 'It is free in preview, works even without an Office subscription, and runs on the web, Windows, Mac, iOS and Android.',
        source:
          'https://support.microsoft.com/en-us/office/rehearse-your-slide-show-with-speaker-coach-cd7fc941-5c3b-498c-a225-83ef3f64f07b',
        checked: '2026-09-18',
      },
      {
        says: 'It covers more than most paid tools: pace, pitch and monotone, filler words, informal speech, euphemisms, wordiness, repetitive words, culturally sensitive language, and on the web even body language and eye contact.',
        source:
          'https://support.microsoft.com/en-us/office/suggestions-from-speaker-coach-25e7d866-c895-4aa1-9b90-089b70a4ea38',
        checked: '2026-09-18',
      },
      {
        says: 'There is nothing to install or upload, because it lives where your deck already is. Open the presentation, then Slide Show and Rehearse with Coach.',
        source:
          'https://support.microsoft.com/en-us/office/rehearse-your-slide-show-with-speaker-coach-cd7fc941-5c3b-498c-a225-83ef3f64f07b',
        checked: '2026-09-18',
      },
    ],
    differences: [
      {
        says: 'Speaker Coach does compare your speech to your slides, for exactly one purpose: catching you reading them aloud. Microsoft is explicit that figures are exempt, writing that if you read a slide of numbers aloud it "won’t identify that action as reading the slide". The number you say is deliberately not weighed against the number on the slide. That gap is the whole reason Flintroom exists.',
        source:
          'https://support.microsoft.com/en-us/office/suggestions-from-speaker-coach-25e7d866-c895-4aa1-9b90-089b70a4ea38',
        checked: '2026-09-18',
      },
      {
        says: 'Nobody asks you anything. Microsoft describes it as a way to "prepare in private", with no simulated audience, no panel and no questions. Flintroom is the opposite: the whole product is the question after the slide.',
        source:
          'https://support.microsoft.com/en-us/office/rehearse-your-slide-show-with-speaker-coach-cd7fc941-5c3b-498c-a225-83ef3f64f07b',
        checked: '2026-09-18',
      },
    ],
    pickThemIf:
      'You want free, instant feedback on how you sound, and you are already rehearsing in PowerPoint. For that job it is hard to beat, and we would not try to talk you out of it.',
    pickUsIf:
      'Your delivery is not the problem. The problem is the person in row two who has read your appendix.',
  },
];

export const hrefFor = (competitor: Competitor): string => `/alternatives/${competitor.slug}`;
