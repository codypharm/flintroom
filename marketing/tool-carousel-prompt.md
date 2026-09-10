# The free-tool carousel prompt

One carousel per tool, for TikTok and Instagram. Paste **The brief** into a
fresh chat, then paste **one tool block** underneath it. Nothing else changes
between posts.

**Why one tool per post rather than a round-up.** A round-up gets saved and
never used. A single calculator taught properly leaves somebody able to do the
arithmetic on paper, which is the only version of this that earns the visit to
the page. The tools also serve different people: a shop owner and a founder
holding SAFEs are not the same viewer, and one post cannot address both.

**Facts in the tool blocks come from the source.** Every input, every formula
and every claim below was read out of `web/src/lib/*.ts` and the matching page.
If a calculator changes, this file is wrong until it is updated, and the
carousel will be wrong after that.

**The link constraint.** TikTok carousels carry no clickable link. The last
slide shows the URL as readable text and points at the bio; the caption repeats
it in plain text. Instagram is the same problem with a different bio.

**Suggested order to post them in.** Break-even and price change have the
widest audience and need no jargon. Runway and LTV:CAC are the founder
staples. Dilution is the most likely to be shared and the most likely to be
argued with, so post it once the account has a few posts behind it. Pacing is
the one that speaks to presenters, which is the app's own audience, so it is
the best one to run near a launch.

---

## The brief

> Paste this part unchanged, then paste one tool block after it.

You are my carousel production lead for Flintroom.

I'm Chukwunonso Ikeji, solo founder of Flintroom, an app that interrogates you
before the room that matters does. Alongside the app I publish free calculators
at flintroom.app/tools. No signup, nothing emailed, nothing stored, no numbers
sent to a server. Each one gives you the figure and then the questions the
figure invites, because the number is rarely the hard part.

I am pre-launch and building in public. I run the engineering, the
distribution and the content myself.

### The job

Produce ONE carousel about ONE free tool, specified in the tool block below.
Not a batch. One post, done properly, where somebody who never visits the page
still walks away able to do the calculation themselves.

### Audience

Whoever the tool block names. They are not marketers, they do not care about my
stack, and they are looking at this because they have to quote a number to
somebody who will push back on it.

### Slide plan

Follow the slide count in the tool block. The shape is always:

1. Hook. Must work alone as a thumbnail, because most people see only this one.
   Name the mistake, not the tool.
2. What this tool gives you that the usual version does not.
3. One slide per input, or per pair of inputs that share a single idea. The
   tool block says which pair with which and why.
4. The equation. Both versions: the one everybody uses, and the one the page
   runs. The contrast is the post. Write both sides AS EQUATIONS, with symbols
   and a small legend defining them. A column that describes the method in
   prose instead of stating it looks like the equation is missing, and it is.
5. The interpretation slide. What the answer means, named in the tool block.
6. Payoff plus the link.

One idea per slide. No slide carrying two thoughts, except the paired input
slides where the pairing is the idea.

### The last slide, exactly

Show the URL as readable text, big enough to type from memory, and say the link
is in the bio. Say it is free, that there is no signup, and that nothing is
stored.

Do not pitch the app hard here. One line at most, and only the true one: the
calculator also gives you the questions the number invites, which is the same
thing the app does out loud.

### Voice

Punchy, concrete, founder-led. Short sentences. Plain words. A dry joke is
welcome; a motivational quote is not. Write like someone explaining something
useful to a friend who has to defend this figure on Thursday.

Hard bans:

- No em dashes anywhere. Use a comma, a colon, or a full stop.
- No "unlock", "elevate", "game-changer", "in today's fast-paced world", "let
  that sink in", rhetorical question stacks.
- No invented metrics, no fake case studies, no "founders who used this raised
  X". I am pre-launch. If a post needs a number, ask me for a real one.
- No claim that the tool predicts anything. It computes what was typed.
- Do not describe Flintroom as a delivery or speech coach. It does not score
  filler words, pace, or eye contact. It attacks the substance of an argument.
- Do not present any of this as financial, legal or tax advice.

### Output

For each slide:

- Slide number
- Headline: max 8 words, readable at thumb speed
- Body: max 35 words
- One line on what should be visually dominant, since these are designed
  rather than screenshotted

Then:

- A caption under 150 words that repeats the URL in plain text
- 6 hashtags, mixing broad and specific
- Three alternative slide-1 hooks, because slide 1 decides whether the other
  slides are seen

---

## Tool block: Runway calculator

**URL:** flintroom.app/tools/runway-calculator
**Audience:** founders, and anyone who has to quote a runway figure
**Slides:** 8

**What it does that the usual version does not.** It gives a date rather than a
count of months. It grows spend and revenue instead of holding both still. It
answers default alive or default dead, which sits on most diligence lists and
which no free calculator seems to compute.

**Inputs.**

1. Cash in the bank. What you can actually spend, net of anything already owed.
   Bank balance and available cash are different numbers, and the gap is where
   a stated runway quietly shortens.
2. Monthly spend. Everything going out: payroll, contractors, tools, rent. This
   is gross burn.
3. Monthly revenue. Everything coming in. Gross burn minus revenue is net burn,
   and runway is always calculated on net burn. Quoting the two
   interchangeably is the most common way a founder and an investor end up
   describing different companies.
4. Spend growth per month. Empty assumes your costs never move, and few
   companies manage that. A company spending 3% more each month hits zero
   earlier than the division says, and the gap widens the further out you look.
5. Revenue growth per month. Empty is the honest floor. Anything above it is a
   claim you will be asked to back, and the follow-up is almost always what the
   last three months actually did.

Pair 2 with 3, because gross versus net burn is one idea and needs both. Pair 4
with 5 for the same reason.

**The equation slide.** Write both sides as equations. A right-hand column
that describes the method in words instead of stating it is the failure mode
here, and it loses the entire contrast the slide exists for.

Everybody:

    runway = C / (S - R)

with S and R frozen for the whole forecast.

This page, month by month, where n is 1 for the month you are standing in:

    S(n)    = S x (1 + g)^(n-1)
    R(n)    = R x (1 + h)^(n-1)
    cash(n) = cash(n-1) - (S(n) - R(n))

    runway  = the first n where cash(n) reaches zero, plus the fraction of
              that month the last of the cash pays for:

    runway  = (n - 1) + cash(n-1) / (S(n) - R(n))

C is cash today, S monthly spend, R monthly revenue, g spend growth, h revenue
growth. Define them in a legend on the slide, small, under the equations.

Two things not to get wrong. The exponent is n-1 rather than n, because month
one is the month you are standing in and runs at today's spend, so growth
starts in month two. And the fractional line is the point of the whole page:
without it the answer is "month 10", which is a count, and with it the answer
is 9.6 months, which is a date.

A worked example belongs on this slide or the one after, because numbers read
faster than symbols. 600,000 in the bank, 55,000 a month, no revenue, spend
growing 3% a month. The division says 10.9 months. Compounded, it is 9.6. Six
weeks that were never there. Those figures come from the page's own algorithm,
so they hold if anybody checks.

**The interpretation slide.** Default alive means revenue covers spend before
cash reaches zero. Default dead means cash gets there first. Most companies are
default dead and that is what a round is for. It changes what the round is: a
choice about speed, or a requirement for survival. Whoever is across the table
knows which one they are looking at.

**What it does not model.** Nothing seasonal, no step changes, no financing.
One steady rate each. If costs jump when you hire, run it twice.

---

## Tool block: Break-even calculator

**URL:** flintroom.app/tools/break-even-calculator
**Audience:** business owners, anyone selling a unit, a seat or a job
**Slides:** 7

**What it does that the usual version does not.** The standard answer is a
number of units, which is correct and hard to act on. This one gives the day of
the month your fixed costs are covered, after which every sale is profit rather
than rent. It also says how far sales could fall before the business stops
working, and when the month falls short it says how many sales short, rather
than reporting a day past the end of the month.

**Inputs.**

1. Fixed costs a month. What you pay whether you sell anything or not: rent,
   salaries, insurance.
2. Price of one sale. Per unit, per job, per month, whatever you sell one of.
3. Gross margin on that sale. What is left after the direct cost of delivering
   it. Asked as a margin rather than a unit cost so services with no unit cost
   still work.
4. Sales in a normal month. Optional, and it is what turns a target into a
   position.

Pair 2 with 3, because price without margin is not a number you can do anything
with.

**The equation slide.**

Everybody:

    Units = Fixed costs / (Price - Unit cost)

This page:

    Contribution per sale = Price x Gross margin
    Units                 = Fixed costs / Contribution per sale
    Day of the month      = (Units / Monthly sales) x 30
    Margin of safety      = (Monthly sales - Units) / Monthly sales

**The interpretation slide.** The day is the one to act on. Break even on day
19 and eleven days of the month are profit. Margin of safety is the same fact
from the other side: how much could go wrong before there is no profit at all.
A margin of safety under about 10% is a business one bad month from trouble,
and that is worth saying plainly.

**What it does not model.** One price, one margin, one product. A mix of
products with different margins needs a blended margin, and blending it is a
judgement rather than arithmetic.

---

## Tool block: Business case ROI

**URL:** flintroom.app/tools/roi-calculator
**Audience:** executives, product managers, and anyone taking a case to a
budget committee
**Slides:** 9

**What it does that the usual version does not.** Every case is presented as
one confident number and attacked with the same question: what if you only get
half of it? This answers that first. Alongside payback and NPV it computes the
share of the projected benefit that actually has to land for the case to break
even, which turns an argument about an optimistic forecast into an argument
about a floor. A floor is a far easier thing to defend.

It also ramps the benefit. Almost every ROI calculator assumes full benefit in
month one, which is never true of anything that has to be rolled out and
learned.

No IRR, deliberately. It needs iteration, it is widely misunderstood, and
nobody has ever won a budget meeting with it.

**Inputs.**

1. One-off cost. Implementation, migration, licences, the first invoice.
2. Monthly running cost. What it costs every month once it is live, including
   the people who run it.
3. Monthly benefit at full run rate. Saved cost or new revenue, once the thing
   is fully working.
4. Months to reach full benefit. Nothing delivers at full rate on day one.
   Empty assumes it does.
5. Time horizon. Three years is what most committees expect. A longer one
   quietly flatters any case.
6. Discount rate a year. Finance may have a number. Ten percent is a common
   default.

Pair 1 with 2. Give 3 and 4 a slide each, because the ramp is the input nobody
else asks for. Pair 5 with 6, since both are the committee's assumptions rather
than yours.

**The equation slide.**

Everybody:

    ROI = (Gain - Cost) / Cost

This page:

    benefit in month n = Monthly benefit x min(1, n / ramp months)
    net in month n     = benefit_n - monthly cost
    Payback            = the month the running total passes the one-off cost
    monthly rate       = (1 + annual rate)^(1/12) - 1
    NPV                = sum of net_n / (1 + monthly rate)^n, minus the one-off
    Benefit needed     = (one-off + present value of running costs)
                         / present value of benefit

**The interpretation slide.** "You need 62% of the projected benefit to land"
is a sentence that survives a hostile room. "The ROI is 240%" is not. Above
100% means the case does not pay back at all on these figures, and the page
reports that honestly rather than hiding it.

**Two details worth a mention in the body copy.** The one-off cost is not
discounted, because it is paid today, and discounting money you are about to
spend is the classic sign error in a hand-rolled NPV. The annual rate is
compounded into a monthly one rather than divided by twelve, which is the
convention a finance team reading over your shoulder will recognise.

---

## Tool block: Pacing and script timing

**URL:** flintroom.app/tools/pacing-calculator
**Audience:** speakers, presenters, anyone with a slot and a script
**Slides:** 7

**What it does that the usual version does not.** The standard tool divides
words by 130 and answers a question nobody is really asking. The question
people run over on is the other way round: I have twenty minutes, what fits? So
this works backwards from the slot. Slot minus questions is speaking time,
speaking time at your pace is a word budget, and the distance between the
budget and the script is the sentence to act on: cut about 350 words.

It also flags dense paragraphs, meaning any paragraph that runs past 45 seconds
without a break. That is about the writing, not the delivery: a paragraph is
where the author gave the speaker somewhere to breathe, so a long one at pace
is where rushing happens.

**Privacy is a selling point here and it is literally true.** The script never
leaves the browser. There is no request to make.

**Inputs.**

1. The script itself, pasted.
2. Pace. Three options, and the numbers rule rather than the names. 110 wpm,
   deliberate: keynotes, board readouts, anything with numbers. 130 wpm,
   conversational: where most presentations land, and the convention every
   competitor uses. 160 wpm, fast pitch: demo day, and hard to follow for long.
3. Slot length. The whole booking.
4. Q&A and everything else. Questions, introductions, the speaker before you
   running over.

Give the pace its own slide, because 110 for a board readout is the number
nobody budgets for. Pair 3 with 4.

**The equation slide.**

Everybody:

    Minutes = Word count / 130

This page:

    Minutes         = Word count / your pace
    Nervous minutes = Minutes / 1.15
    Speaking time   = Slot - Q&A
    Word budget     = Speaking time x your pace
    Words to cut    = Word count - Word budget

**The interpretation slide.** Under pressure people speed up, not down, which
is why the nervous figure is shorter rather than longer. Fifteen percent is a
defensible middle of the reported range: enough to matter over ten minutes, not
so much that it reads as a scare figure. A script written to fill the slot
exactly will finish early on the day, and that is a worse problem than it
sounds, because the time gets filled with unrehearsed talking.

---

## Tool block: LTV:CAC and payback

**URL:** flintroom.app/tools/ltv-cac-calculator
**Audience:** founders and operators, anyone quoting a ratio in a deck
**Slides:** 8

**What it does that the usual version does not.** The ratio is the number
people quote and the softest one in any deck, because lifetime value assumes a
customer lifetime nobody has lived through yet. Compute it from 3% monthly
churn and you have assumed the average customer stays 33 months, which is
nearly three years. Most companies quoting that have not existed for three
years. This page puts the assumed lifetime next to how long the company has
been operating, and says so when the first is longer than the second.

It also refuses two common errors: value is gross profit rather than revenue,
and monthly churn compounds into an annual figure rather than being multiplied
by twelve.

**Inputs.**

1. Monthly revenue per customer. What one customer pays in a month, on average.
2. Gross margin. What is left after the cost of serving them. Left empty, this
   counts revenue as value, which is the error.
3. Monthly churn. The share of customers who leave in a month.
4. Cost to acquire one customer. All of it: ad spend, plus the salaries of the
   people doing the acquiring.
5. How long you have been operating. What the assumed lifetime gets measured
   against.

Pair 1 with 2. Churn gets its own slide, because it is where the lifetime comes
from and the whole post turns on it. CAC gets its own slide, because "all of
it" is the part people get wrong. Input 5 belongs with the interpretation
slide.

**The equation slide.**

Everybody:

    LTV = ARPU / churn,  then  LTV / CAC

This page:

    Monthly contribution = Revenue per customer x Gross margin
    Average lifetime     = 1 / Monthly churn
    LTV                  = Monthly contribution x Average lifetime
    Ratio                = LTV / CAC
    Payback              = CAC / Monthly contribution
    Annual churn         = 1 - (1 - monthly churn)^12

**The interpretation slide.** 3% monthly churn is 31% a year, not 36%. And a
33 month assumed lifetime from a company that is 14 months old is a forecast
wearing the clothes of a measurement. Naming the duration your ratio rests on
is what turns it back into a claim you can defend, and doing it before somebody
else does is the whole trick.

---

## Tool block: Dilution calculator

**URL:** flintroom.app/tools/dilution-calculator
**Audience:** founders holding SAFEs, anyone about to price a round
**Slides:** 8

**What it does that the usual version does not.** Most of them divide your
stake by the post-money and stop. This one converts SAFEs, pre-money or post,
carves the option pool on the side it actually sits on, and then attributes the
points you gave up to the three things that took them. That attribution is the
post: founders usually blame the investor, and the pool and the notes are
frequently the larger share.

Everything is proportional, so it runs on percentages and never asks for a
share count. A founder holding SAFEs usually has no formal cap table yet. They
know they own 62%.

**Inputs.**

1. What you own today, as a percentage of the pre-round cap table.
2. Your SAFEs: amount, valuation cap, discount, and post-money or pre-money.
   Post-money is the YC standard since 2018 and the default. Its percentage is
   fixed at conversion, so a second post-money SAFE dilutes the founders rather
   than the first note. A pre-money note dilutes the other notes too.
3. Pre-money valuation.
4. Amount being raised.
5. Option pool after the round, as a percentage.
6. Where the pool sits: pre-money or post-money. Pre-money is the standard ask
   and it dilutes existing holders only, which is exactly why it is the
   standard ask.

Give the SAFE terms their own slide. Pair 3 with 4. Give the pool its own
slide, and make the pre versus post distinction the point of it.

**The equation slide.**

Everybody:

    Your new stake = Your stake x (pre-money / post-money)

This page:

    Investor takes       = Raise / (Pre-money + Raise)
    A note converts at   = the lower of its cap and pre-money x (1 - discount)
    A pre-money pool is carved out of the pre-money slice, so it costs the
    existing holders and leaves the investor untouched
    Points you gave up   = stake before - stake after
    split across SAFEs, pool and investor in the order it happens

**The interpretation slide.** Points are not percent. Sixty to forty-eight is
twelve points and a twenty percent fall in what you own, and the two get
confused constantly. Then the attribution: name which of the three took the
most, because the answer is often the option pool, and the pool is the one
line in a term sheet founders negotiate least.

**Say this plainly on the last slide.** A cap and a discount are not combined.
The holder takes whichever gives more shares, which is the lower valuation.
Real pre-money conversion with several notes is circular, so this uses the
convention every comparable tool uses: right to a fraction of a point, and not
a legal document.

---

## Tool block: Price change calculator

**URL:** flintroom.app/tools/price-change-calculator
**Audience:** business owners, operators, anyone about to discount
**Slides:** 7

**What it does that the usual version does not.** The question people ask
before changing a price is will they leave, which nobody can answer. The
question they can answer, and almost never do, is how many would have to leave
before the change stopped being worth it. That is arithmetic rather than
judgement, and it is surprising in both directions. At a 30% margin, a 10% rise
survives losing about a quarter of the customers. A 10% discount needs half
again as many customers just to stand still.

The discount half is the more useful, because discounting is the more common
decision and by far the more damaging.

**This does not predict whether anybody will leave.** That is elasticity, it
needs data the page cannot ask for, and inventing it would be inventing the
most important input. What comes back is the threshold, not the outcome. Say
this on a slide, not in small print.

**Inputs.**

1. Current price. Per unit, per seat, per month.
2. Gross margin at that price. What is left after the direct cost of
   delivering it.
3. Price change. Negative for a discount. A cut of 10 is entered as -10.
4. Customers or units a month. Optional. It turns the percentage into a number
   of customers, which is the version people act on.

Pair 1 with 2.

**The equation slide.**

Everybody: nothing. This is the calculation almost nobody does.

This page:

    Unit cost              = Price x (1 - Gross margin)      and it does not move
    New price              = Price x (1 + Change)
    Contribution before    = Price - Unit cost
    Contribution after     = New price - Unit cost
    Volume change needed   = (Contribution before / Contribution after) - 1

**The interpretation slide.** The unit cost is held still across the change,
and that is the point most versions get wrong. Recomputing the cost from the
new price makes every price rise look free. And a discount deeper than the
margin has no answer at all: every sale is made below cost, and no volume
rescues it.
