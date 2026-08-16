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
    # The Technical Skeptic
    "technology": ("technology", "tech", "stack", "build", "built", "engineering"),
    "architecture": ("architecture", "infrastructure", "scale", "scaling", "latency"),
    "security": ("security", "secure", "soc", "penetration", "breach", "vulnerability"),
    "defensibility": ("defensibility", "moat", "patent", "proprietary", "replicate"),
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
    "resourcing": ("resourcing", "resources", "budget", "capacity", "bandwidth"),
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
    "data": ("retention", "residency", "encryption", "storage"),
}


def terms_for(domain: str) -> tuple[str, ...]:
    """The words that signal a domain, or just the domain itself.

    A domain with no entry still matches its own name, so an archetype declaring
    something this table has never heard of degrades to the old behaviour rather
    than to silence. That matters because archetypes are configuration: somebody
    will add one before they add its vocabulary.
    """
    return DOMAIN_TERMS.get(domain, (domain,))
