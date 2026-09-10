import db


def unique_amount(base_price: int) -> int:
    """Append a small unique suffix to the price so a manual bank statement
    lookup can match a deposit to an order unambiguously (same trick as the
    reference bot: 60000 -> 60002).
    """
    for suffix in range(1, 100):
        candidate = base_price + suffix
        if not db.amount_in_use(candidate):
            return candidate
    # Extremely unlikely fallback if 99 orders for the exact same price are
    # all pending review simultaneously.
    return base_price + 1
