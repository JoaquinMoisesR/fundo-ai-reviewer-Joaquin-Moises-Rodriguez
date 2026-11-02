"""Score the keyword engine and the reviewer against the ground truth.

A label error is MATERIAL when it changes something the offer or the risk model reads:
revenue yes/no, or a group that feeds a feature (nsf, overdraft, active_advance,
high-risk). Example of an immaterial error: a Square payout labeled 'none' instead of
'auto_deposit' is still revenue, so it moves no number.
"""
from credit_impact import features
from taxonomy import HIGH_RISK_GROUPS

FEATURE_GROUPS = {"nsf", "overdraft", "active_advance"} | HIGH_RISK_GROUPS


def _same(a, b):
    return a["group"] == b["group"] and a["is_business"] == b["is_business"]


def is_material(label, truth):
    if label["is_revenue"] != truth["is_revenue"]:
        return True
    in_a, in_b = label["group"] in FEATURE_GROUPS, truth["group"] in FEATURE_GROUPS
    return (in_a or in_b) and label["group"] != truth["group"]


def evaluate(businesses, truth, legacy, review):
    final = review["labels"]
    pats = [p for r in review["results"] for p in r["patterns"]]
    amount = {t["transaction_id"]: t["amount"] for b in businesses for t in b["transactions"]}

    # ---- revenue dollar error per business
    revenue_rows = []
    for b in businesses:
        tr = features(b, truth)["monthly_revenue"]
        lg = features(b, legacy)["monthly_revenue"]
        rv = features(b, final)["monthly_revenue"]
        revenue_rows.append({"business_id": b["business_id"], "truth": tr,
                             "legacy_error": lg - tr, "reviewed_error": rv - tr})

    # ---- transaction-level label quality
    ids = list(truth)
    def counts(labels):
        wrong = [i for i in ids if not _same(labels[i], truth[i])]
        mat = [i for i in wrong if is_material(labels[i], truth[i])]
        return {"label_errors": len(wrong), "material_errors": len(mat),
                "material_dollars": round(sum(abs(amount[i]) for i in mat), 2)}

    # ---- flags (pattern level -> transaction level)
    flagged_tx, applied_tx, needs_human_tx, material_tx = set(), set(), set(), set()
    for p in pats:
        if p.get("material"):
            material_tx |= set(p["tx_ids"])
        if p.get("flagged"):
            flagged_tx |= set(p["tx_ids"])
        if p.get("applied"):
            applied_tx |= set(p["tx_ids"])
        if p.get("needs_human"):
            needs_human_tx |= set(p["tx_ids"])
    legacy_wrong = {i for i in ids if not _same(legacy[i], truth[i])}
    legacy_material = {i for i in legacy_wrong if is_material(legacy[i], truth[i])}
    hard_neg = {i for i in ids if truth[i]["tag"] == "hard_neg"}

    flag_stats = {
        "patterns_total": len(pats),
        "patterns_flagged": sum(1 for p in pats if p.get("flagged")),
        "patterns_unreviewed": sum(1 for p in pats if p.get("status") == "unreviewed"),
        "tx_flagged": len(flagged_tx),
        "tx_flagged_correctly": len(flagged_tx & legacy_wrong),
        "tx_false_flags": len(flagged_tx - legacy_wrong),
        "hard_negatives": len(hard_neg),
        "hard_negatives_flagged": len(flagged_tx & hard_neg),
        "hard_negatives_flagged_material": len(material_tx & hard_neg),
        "patterns_flagged_material": sum(1 for p in pats if p.get("material")),
        "tx_material_flags": len(material_tx),
        "tx_material_flags_correct": len(material_tx & legacy_material),
        "tx_material_false_flags": len(material_tx - legacy_wrong),
        "legacy_material_errors": len(legacy_material),
        "legacy_material_errors_flagged": len(legacy_material & flagged_tx),
        "applied_corrections_tx": len(applied_tx),
        "applied_corrections_right": sum(1 for i in applied_tx if _same(final[i], truth[i])),
        "tx_routed_to_human": len(needs_human_tx),
    }

    # ---- adversarial cases: what happened to each
    adversarial = []
    for p in pats:
        tags = {truth[i]["tag"] for i in p["tx_ids"]}
        if "adversarial" in tags:
            t = truth[p["tx_ids"][0]]
            adversarial.append({
                "description": p["description"], "truth_group": t["group"],
                "truth_is_revenue": t["is_revenue"], "legacy": p["legacy"],
                "proposed": p.get("proposed"), "applied": p.get("applied"),
                "model_injection_flag": p.get("model_injection_flag"),
                "code_injection_flag": p["code_injection_flag"],
                "blocked_by_guard": p.get("blocked_by_injection_guard"),
                "final_correct": _same(final[p["tx_ids"][0]], t), "reason": p.get("reason")})

    # ---- reviewer mistakes to read (pattern level)
    mistakes = []
    for p in pats:
        t = truth[p["tx_ids"][0]]
        legacy_ok = _same(legacy[p["tx_ids"][0]], t)
        if p.get("status") != "reviewed":
            continue
        if p["flagged"] and legacy_ok:
            kind = "false flag (legacy was right)" + ("" if p["material"] else ", immaterial: filtered by code")
        elif not p["flagged"] and not legacy_ok:
            kind = "missed error" + (" (material)" if is_material(legacy[p["tx_ids"][0]], t) else " (immaterial)")
        elif p["flagged"] and not _same(p["proposed"], t):
            kind = "flagged, but proposed label also wrong"
        else:
            continue
        mistakes.append({"kind": kind, "business_id": p["business_id"], "description": p["description"],
                         "count": p["count"], "total": p["total"], "legacy": p["legacy"],
                         "proposed": p.get("proposed"), "truth": {k: t[k] for k in ("group", "is_business", "is_revenue")},
                         "confidence": p.get("confidence"), "reason": p.get("reason")})

    return {"revenue": revenue_rows, "legacy": counts(legacy), "reviewed": counts(final),
            "flags": flag_stats, "adversarial": adversarial, "mistakes": mistakes}
