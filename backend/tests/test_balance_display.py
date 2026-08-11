"""How a balance is presented.

Two rules from Product.md §4.6 and the Metering Rules: never show a depleting
counter, and never let the number lie. Seconds are charged exactly; what the
user sees is floored, so they always have slightly more than promised and never
less.

These are pure functions over a Balance — the presentation rule lives in one
place rather than being re-derived in each client.
"""

from app.modules.billing.schemas import Balance


def balance(allowance: int = 0, free: int = 0, topup: int = 0) -> Balance:
    return Balance(allowance_seconds=allowance, free_seconds=free, topup_seconds=topup)


def test_remaining_minutes_floors_so_the_user_always_has_more_than_shown():
    """605 seconds reads as 10 minutes, not 11.

    Rounding up would promise a minute that is not there. Flooring is generous
    in the user's favour without being a lie.
    """
    assert balance(allowance=605).remaining_minutes == 10


def test_an_overdrawn_balance_never_displays_as_negative():
    """A grace overdraft is real in the ledger and invisible in the UI.

    The user was allowed to finish their session past zero as a kindness
    (Product.md §4.5). Showing them "-2 minutes" would present that kindness as
    a debt, and the overdraft is forgiven at settlement anyway.
    """
    assert balance(allowance=-120).remaining_minutes == 0


def test_a_sub_minute_balance_is_distinguishable_from_empty():
    """59 seconds and 0 seconds both floor to "0 minutes" and are not the same.

    One of them can still start a session. Without this distinction the UI has
    to either lie ("no minutes left") or invent its own rule from the raw
    seconds — and Product.md §4.6 forbids showing a depleting counter, so the
    seconds must not leak into the interface.
    """
    nearly_empty = balance(allowance=59)
    empty = balance()

    assert nearly_empty.remaining_minutes == empty.remaining_minutes == 0
    assert nearly_empty.has_time_remaining is True
    assert empty.has_time_remaining is False
