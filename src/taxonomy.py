"""Shared vocabulary: the 13 keyword groups and the revenue rule.

Kept in one place so the data generator, the keyword engine, the reviewer and
the credit-impact code can never disagree about what a group means.
"""

GROUPS = [
    "not_avg_monthly_revenue",
    "nsf",
    "overdraft",
    "internal_transfer",
    "ucc",
    "active_advance",
    "auto_deposit",
    "revenue_verification",
    "hr_gambling",
    "hr_bankruptcy",
    "hr_debt_settlement",
    "hr_garnishment",
    "hr_other",
]
NO_GROUP = "none"
ALL_LABELS = GROUPS + [NO_GROUP]

# Groups that block a credit from counting as revenue (our assumption, documented
# in SOLUTION.md: money that is not earned sales, or that is not durable income).
EXCLUDING_GROUPS = {
    "not_avg_monthly_revenue",
    "internal_transfer",
    "active_advance",
    "nsf",
    "overdraft",
}

# Groups counted as "high risk" when they are debits.
HIGH_RISK_GROUPS = {g for g in GROUPS if g.startswith("hr_")}


def is_revenue(amount: float, is_business: bool, group: str) -> bool:
    """Plaid sign convention: amount < 0 is money IN (credit), > 0 is money OUT.

    Revenue = business credit and no excluding group.
    """
    return amount < 0 and is_business and group not in EXCLUDING_GROUPS
