"""Monthly interrogation allowance per entitlement tier.

Figures from Product.md §4.4. They are policy, not arithmetic — they move when
pricing moves, and pricing cannot move without the §4.3 cost-instrumentation
task behind it.

The free tier is deliberately absent rather than set to zero minutes: its 15
minutes are *lifetime*, granted once at signup into the free bucket, and nothing
about it renews monthly.
"""

MONTHLY_ALLOWANCE_SECONDS: dict[str, int] = {
    "starter": 90 * 60,
    "pro": 180 * 60,
    "pro_annual": 180 * 60,
    "teams": 90 * 60,
}

#: Granted once at signup, never renewed. Product.md §4.4.
FREE_TIER_LIFETIME_SECONDS = 15 * 60

#: The tier every account starts on. Not a key in the table above: the free
#: tier's minutes are lifetime rather than monthly, so it has no renewing
#: allowance to look up.
FREE_TIER = "free"
