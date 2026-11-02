"""Legacy keyword engine: the deliberately imperfect labeler the LLM reviews.

How it works (on purpose, the way a real legacy engine works):
  1. Normalize the description: uppercase, punctuation -> space.
  2. For each group, check if any keyword appears starting at a word boundary
     (prefix match: "BET" matches "BETTY", but "NSF" does not match "TRANSFER").
  3. If several groups match, PRECEDENCE decides the winner (first in the list).
  4. Business/personal: personal if a personal keyword appears, else business.
  5. Revenue: taxonomy.is_revenue (business credit and no excluding group).

Known flaws, kept on purpose because they are the ones the brief describes:
  - Keywords that contain punctuation ("KABBAGE:", "SQ *", "COINBASE.COM") are
    compared against a text whose punctuation was removed, so they never match.
  - Prefix match: "BET" fires on "BETTY'S BAKERY" and "BETTING SUPPLIES".
  - Same counterparty, different meaning: "SQUARE" matches both Square Inc sales
    and Square Capital loans, and it is only listed under auto_deposit.
  - "TRANSFER FROM" wins over "CAPITAL ADVANCE" by precedence.
  - Any "ZELLE" is marked personal, even customers paying the business.
  - It cannot see recurrence (a fixed daily debit to an unknown funder).

Run:  python src/keyword_engine.py   (prints a per-business accuracy vs truth)
"""
import re

from taxonomy import is_revenue

ENGINE_VERSION = "kw-1.0"

# Order = precedence. The first group whose keywords match wins.
KEYWORDS = [
    ("nsf", ["NSF", "INSUFFICIENT FUNDS", "RETURNED ITEM"]),
    ("hr_bankruptcy", ["BANKRUPTCY", "CH13", "CHAPTER 13", "CHAPTER 7"]),
    ("hr_garnishment", ["GARNISH", "LEVY"]),
    ("hr_debt_settlement", ["DEBT RELIEF", "DEBT SETTLEMENT", "CONSOLIDATION"]),
    ("ucc", ["UCC"]),
    ("internal_transfer", ["TRANSFER FROM", "TRANSFER TO SAVINGS", "TRANSFER TO CHECKING"]),
    ("overdraft", ["OVERDRAFT", "OD FEE"]),
    ("active_advance", ["YELLOWSTONE", "CAPITAL ADVANCE", "CASH ADVANCE", "KABBAGE:",
                        "MCA ", "DAILY ACH", "MERCHANT FUNDING"]),
    ("hr_gambling", ["CASINO", "DRAFTKINGS", "FANDUEL", "BET"]),
    ("hr_other", ["COINBASE.COM", "PAWN", "PAYDAY"]),
    ("not_avg_monthly_revenue", ["REFUND", "REVERSAL"]),
    ("revenue_verification", ["CLAIM PMT", "HEALTHCARE EFT", "INSURANCE"]),
    ("auto_deposit", ["SQUARE", "SQ *", "STRIPE", "SHOPIFY", "CLOVER", "FISERV",
                      "DOORDASH", "PAYPAL"]),
]
PERSONAL_KEYWORDS = ["VENMO", "ZELLE", "PERSONAL", "OWNER"]


def normalize(text: str) -> str:
    """Uppercase and turn every non-alphanumeric char into a space."""
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]", " ", text.upper())).strip()


def _hits(text: str, keywords: list) -> bool:
    return any(re.search(r"(?<![A-Z0-9])" + re.escape(k), text) for k in keywords)


def label(tx: dict) -> dict:
    """Label one Plaid transaction. Returns group, is_business, is_revenue, matched."""
    text = normalize(tx["name"])
    matched = [g for g, kws in KEYWORDS if _hits(text, kws)]
    group = matched[0] if matched else "none"
    is_business = not _hits(text, PERSONAL_KEYWORDS)
    return {
        "group": group,
        "is_business": is_business,
        "is_revenue": is_revenue(tx["amount"], is_business, group),
        "matched": matched,
    }


def label_all(businesses: list) -> dict:
    """transaction_id -> legacy label, for every transaction in the dataset."""
    return {tx["transaction_id"]: label(tx) for b in businesses for tx in b["transactions"]}


if __name__ == "__main__":
    import json
    from pathlib import Path

    data = Path(__file__).resolve().parent.parent / "data"
    businesses = json.loads((data / "transactions.json").read_text())
    truth = json.loads((data / "truth.json").read_text())
    labels = label_all(businesses)
    for b in businesses:
        txs = b["transactions"]
        wrong = [t for t in txs if (labels[t["transaction_id"]]["group"], labels[t["transaction_id"]]["is_business"])
                 != (truth[t["transaction_id"]]["group"], truth[t["transaction_id"]]["is_business"])]
        rev_wrong = sum(1 for t in txs if labels[t["transaction_id"]]["is_revenue"] != truth[t["transaction_id"]]["is_revenue"])
        print(f"{b['business_id']:28s} txs={len(txs):4d} label_errors={len(wrong):3d} revenue_errors={rev_wrong:3d}")
        for name in sorted({t["name"] for t in wrong})[:6]:
            print("     ", name[:80])
