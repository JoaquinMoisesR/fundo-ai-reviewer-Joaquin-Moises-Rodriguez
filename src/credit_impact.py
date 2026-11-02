"""Credit features, the offer rule, and the mislabel-rate simulation. Pure code, no LLM.

Features per business, from any set of labels (legacy, reviewed, or truth):
  revenue_share      revenue / total deposits (credits)
  nsf_count, od_count
  high_risk_share    high-risk debits / total debits
  monthly_revenue    revenue over the window / (window days / 30)
  funder_daily       active_advance debits / business days in the window
                     (average daily amount already committed to other funders)
Offer (the brief's rule):
  offer = max(0, 1.2 * monthly_revenue - 20 * funder_daily); 0 if nsf_count > 5
"""
import random
from datetime import date, timedelta

from taxonomy import ALL_LABELS, HIGH_RISK_GROUPS, is_revenue

NSF_CUTOFF = 5


def _window(txs):
    ds = [date.fromisoformat(t["date"]) for t in txs]
    lo, hi = min(ds), max(ds)
    days = (hi - lo).days + 1
    bdays = sum(1 for i in range(days) if (lo + timedelta(i)).weekday() < 5)
    return days, bdays


def features(business: dict, labels: dict) -> dict:
    txs = business["transactions"]
    days, bdays = _window(txs)
    dep = rev = deb = hr = adv = 0.0
    nsf = od = 0
    for t in txs:
        lab = labels[t["transaction_id"]]
        a = t["amount"]
        if a < 0:
            dep += -a
            if lab["is_revenue"]:
                rev += -a
        else:
            deb += a
            if lab["group"] in HIGH_RISK_GROUPS:
                hr += a
            if lab["group"] == "active_advance":
                adv += a
            if lab["group"] == "nsf":
                nsf += 1
            if lab["group"] == "overdraft":
                od += 1
    monthly = rev / (days / 30)
    daily = adv / bdays
    return {"revenue_share": rev / dep if dep else 0.0, "nsf_count": nsf, "od_count": od,
            "high_risk_share": hr / deb if deb else 0.0, "monthly_revenue": monthly,
            "funder_daily": daily, "offer": offer(monthly, daily, nsf)}


def offer(monthly_revenue: float, funder_daily: float, nsf_count: int) -> float:
    if nsf_count > NSF_CUTOFF:
        return 0.0
    return max(0.0, 1.2 * monthly_revenue - 20 * funder_daily)


def table(businesses: list, label_sets: dict) -> list:
    """label_sets: {"legacy": {...}, "reviewed": {...}, "truth": {...}} -> rows."""
    rows = []
    for b in businesses:
        row = {"business_id": b["business_id"]}
        for name, labels in label_sets.items():
            row[name] = features(b, labels)
        rows.append(row)
    return rows


# ------------------------------------------------------------- mislabel simulation
def _relabel(tx, group, is_business):
    return {"group": group, "is_business": is_business,
            "is_revenue": is_revenue(tx["amount"], is_business, group)}


# Each scenario: which true transactions are eligible, and what the wrong label is.
SCENARIOS = {
    "random (any label -> any other)": (lambda t, L: True, None),
    "false revenue (non-revenue credit -> revenue)":
        (lambda t, L: t["amount"] < 0 and not L["is_revenue"], ("none", True)),
    "missed revenue (sale -> excluded)":
        (lambda t, L: L["is_revenue"], ("not_avg_monthly_revenue", True)),
    "missed advance (funder debit -> none)":
        (lambda t, L: t["amount"] > 0 and L["group"] == "active_advance", ("none", True)),
    "false advance (ordinary debit -> advance)":
        (lambda t, L: t["amount"] > 0 and L["group"] == "none", ("active_advance", True)),
    "false NSF (ordinary debit -> NSF)":
        (lambda t, L: t["amount"] > 0 and L["group"] == "none", ("nsf", True)),
    "missed NSF (NSF fee -> none)":
        (lambda t, L: L["group"] == "nsf", ("none", True)),
}


def simulate(businesses: list, truth: dict, rates=(0.02, 0.05, 0.10), runs=200, seed=11):
    """Corrupt the TRUE labels at a given rate and measure how features and offer move.

    Rate = share of the business's transactions that get mislabeled, drawn only from
    the transactions where that error type is possible (capped at all of them).
    Reports mean signed offer change, mean |change|, and how often the decision
    flips (offer > 0 <-> offer == 0), averaged over businesses and runs.
    """
    rng = random.Random(seed)
    base = {b["business_id"]: features(b, truth) for b in businesses}
    out = []
    for name, (eligible, wrong) in SCENARIOS.items():
        for rate in rates:
            d_off, a_off, flips, d_rev, d_daily, d_nsf, n = 0.0, 0.0, 0, 0.0, 0.0, 0.0, 0
            for _ in range(runs):
                for b in businesses:
                    txs = b["transactions"]
                    pool = [t for t in txs if eligible(t, truth[t["transaction_id"]])]
                    k = min(len(pool), round(rate * len(txs)))
                    labels = dict(truth)
                    for t in rng.sample(pool, k):
                        L = truth[t["transaction_id"]]
                        if wrong is None:
                            g = rng.choice([x for x in ALL_LABELS if x != L["group"]])
                            labels[t["transaction_id"]] = _relabel(t, g, L["is_business"])
                        else:
                            labels[t["transaction_id"]] = _relabel(t, *wrong)
                    f, f0 = features(b, labels), base[b["business_id"]]
                    d = f["offer"] - f0["offer"]
                    d_off += d; a_off += abs(d); n += 1
                    flips += (f["offer"] > 0) != (f0["offer"] > 0)
                    d_rev += f["monthly_revenue"] - f0["monthly_revenue"]
                    d_daily += f["funder_daily"] - f0["funder_daily"]
                    d_nsf += f["nsf_count"] - f0["nsf_count"]
            out.append({"scenario": name, "rate": rate, "mean_offer_change": d_off / n,
                        "mean_abs_offer_change": a_off / n, "decision_flip_rate": flips / n,
                        "mean_monthly_revenue_change": d_rev / n,
                        "mean_funder_daily_change": d_daily / n, "mean_nsf_change": d_nsf / n})
    return out
