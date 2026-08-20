"""What a domain sounds like when somebody says it out loud.

An archetype declares the domains it owns — `margin`, `headcount`, `compliance`.
Those are canonical names, and they have to be: `docs/auditor-grounding.md` has
each derivation pack declare the domain that owns a figure, and the two
vocabularies must agree or targeted interruption routes to nobody.

But people do not talk in canonical names. Measured against fifteen sentences of
the kind a presenter actually says, matching on the canonical word alone routed
**7%** of them — `ARR` is revenue, *"the team is eight people"* is headcount,
*"SOC 2 before they'll sign"* is compliance, and *"spending more to acquire each
customer than we make back"* is the CFO's entire reason for existing. The rest
fell through to rotation, which is round-robin with an occasional coincidence.

So this maps each canonical domain to the words that signal it. It is a lookup
table and it is meant to look like one: no stemming, no embeddings, no model.
Every entry is a judgement somebody can read and disagree with, which is the
property that matters for something that decides who speaks.

**It will always be incomplete.** The real fix is routing on the claims the
Auditor already extracts from live speech — those carry the metric explicitly,
so a figure about acquisition cost arrives labelled rather than guessed at. This
is the honest cheap version until that exists.
"""

from __future__ import annotations

#: Canonical domain → the words that signal it, including the canonical one.
#:
#: Single words only. Phrases would need tokenisation this deliberately does not
#: do, and the words below are chosen to be the ones that carry the meaning on
#: their own: "acquire" is about acquisition cost in a room like this, and
#: "onboarding" is about adoption whatever the sentence around it says.
DOMAIN_TERMS: dict[str, tuple[str, ...]] = {
    # The CFO
    "margin": ("margin", "margins", "gross", "unit", "economics", "profitability"),
    "revenue": ("revenue", "revenues", "arr", "mrr", "topline", "bookings", "sales"),
    "cost": (
        "cost", "costs", "spend", "spending", "burn", "acquire", "acquisition",
        "cac", "payback", "expense", "expenses",
    ),
    "valuation": ("valuation", "raise", "raising", "round", "dilution", "equity"),
    "runway": ("runway", "months", "breakeven", "profitable", "cash"),
    "headcount": ("headcount", "hiring", "hire", "team", "people", "staff", "engineers"),
    # The Technical Skeptic.
    #
    # **Two vocabularies per domain, deliberately.** She was written owning
    # `technology`, `architecture` and `security`, which meant she could only be
    # reached by software words — and seated against a medical supply business
    # she had nothing legitimate to ask, so she invented something (#81). The
    # LIBRARY docstring's own rule is that a persona is a stance and never an
    # industry.
    #
    # The fix is not to take the software away. Her whole value against a
    # deployment is knowing what a deployment is. So each domain answers to the
    # general word AND the specific one: "supplier" and "database" are both
    # single points of failure, and she is the person who asks what happens when
    # either goes down.
    "feasibility": (
        "feasibility", "works", "working", "prototype", "pilot", "manual",
        "automated", "process", "build", "built", "engineering", "technology",
        "tech", "stack", "code",
    ),
    "capacity": (
        "capacity", "volume", "throughput", "load", "peak", "demand", "surge",
        "scale", "scaling", "latency", "servers", "infrastructure",
        "architecture",
    ),
    "resilience": (
        "resilience", "fails", "failure", "outage", "downtime", "backup",
        "redundancy", "spoilage", "shortage", "supplier", "suppliers",
        "security", "breach", "soc", "vulnerability",
    ),
    "defensibility": (
        "defensibility", "moat", "patent", "proprietary", "replicate", "copy",
        "copied", "barrier", "exclusive",
    ),
    # The Champion
    "proof": ("proof", "evidence", "data", "results", "benchmark", "study"),
    "references": ("reference", "references", "testimonial", "case", "logo", "logos"),
    # The Growth Maximalist
    "market": ("market", "tam", "segment", "vertical", "opportunity"),
    "growth": ("growth", "growing", "grew", "traction", "trajectory", "velocity"),
    "timing": ("timing", "now", "window", "wave", "shift"),
    "competition": (
        "competition", "competitor", "competitors", "competing", "incumbent",
        "alternative", "rivals",
    ),
    # The Internal Blocker
    # `capacity` is deliberately absent, and it used to be here. Generalising
    # the Technical Skeptic gave her a `capacity` domain, and a word in two
    # lists is resolved by whichever key this dict happens to reach first —
    # which is not a decision anybody made. Split on which question the word
    # actually asks: "we are at capacity" is most often about what an operation
    # can take, and she is the one who asks what happens when it is exceeded.
    # The Blocker keeps `bandwidth`, which is the word a team uses about itself.
    "resourcing": ("resourcing", "resources", "budget", "bandwidth"),
    "dependencies": ("dependencies", "dependency", "blocked", "waiting", "prerequisite"),
    "ownership": ("ownership", "owns", "owner", "responsible", "accountable"),
    # The Customer Advocate
    "customers": ("customers", "customer", "users", "user", "buyers", "clients"),
    "adoption": ("adoption", "onboarding", "activation", "rollout", "usage"),
    "retention": ("retention", "churn", "renewal", "renewals", "expansion", "nps"),
    "usability": ("usability", "ux", "friction", "confusing", "intuitive"),
    # The Risk Officer
    "compliance": ("compliance", "compliant", "regulation", "regulatory", "audit"),
    "legal": ("legal", "liability", "contract", "indemnity", "terms"),
    "privacy": ("privacy", "gdpr", "consent", "pii", "personal"),
    # `retention` is deliberately absent, and it used to be here — where it
    # never once fired, because the Customer Advocate lists the same word and
    # gets there first. The collision test found it. Removing it rather than
    # moving it: a presenter who says "retention" in a rehearsal means churn
    # almost every time, and the Risk Officer's sense needs the two-word phrase
    # "data retention" that this table is single-word by design.
    "data": ("residency", "encryption", "storage"),
}


def terms_for(domain: str) -> tuple[str, ...]:
    """The words that signal a domain, or just the domain itself.

    A domain with no entry still matches its own name, so an archetype declaring
    something this table has never heard of degrades to the old behaviour rather
    than to silence. That matters because archetypes are configuration: somebody
    will add one before they add its vocabulary.
    """
    return DOMAIN_TERMS.get(domain, (domain,))


#: What each domain is called on a screen.
#:
#: The keys are routing identifiers and read like column names — `defensibility`,
#: `resourcing`, `proof`. Shown raw in the authoring picker they ask somebody to
#: guess at the thing that decides when their panelist interrupts.
#:
#: **Not a wholesale rewrite.** `Margin`, `Runway` and `Retention` are the words
#: this audience uses, and replacing them would flatten terminology they
#: genuinely know — `clarify`'s rule, and the reason most of these are simply the
#: key with a capital. What earns different words are the handful nobody can
#: rank against each other on sight.
#:
#: Same move as `VOICE_BLURBS`: the words that make a thing choosable stop being
#: a comment the moment a user has to choose between them.
DOMAIN_LABELS: dict[str, str] = {
    "adoption": "Adoption",
    "capacity": "Capacity at scale",
    "competition": "Competitors",
    "compliance": "Compliance",
    "cost": "Costs",
    "customers": "Customers",
    "data": "Data handling",
    "defensibility": "What stops a copy",
    "dependencies": "Dependencies",
    "feasibility": "Whether it works",
    "growth": "Growth",
    "headcount": "Headcount",
    "legal": "Legal exposure",
    "margin": "Margin",
    "market": "Market size",
    "ownership": "Who owns what",
    "privacy": "Privacy",
    "proof": "Evidence",
    "references": "References",
    "resilience": "What breaks",
    "resourcing": "Who does the work",
    "retention": "Retention",
    "revenue": "Revenue",
    "runway": "Runway",
    "timing": "Timing",
    "usability": "Usability",
    "valuation": "Valuation",
}
