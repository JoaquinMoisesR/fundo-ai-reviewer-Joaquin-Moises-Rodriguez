"""Experiments behind the model and prompt choices. Results are cached like the main run.

  A. main configuration          claude-opus-5-5, Plaid category in the prompt
  B. ablation: no Plaid category  does the reviewer just copy Plaid's own category?
  C. cheaper model               claude-haiku-5-5 (~40x cheaper per token)

  python src/experiments.py --offline   -> output/experiments.md
"""
import argparse
import json
import sys
from pathlib import Path

import evaluate
import keyword_engine
import reviewer

ROOT = Path(__file__).resolve().parent.parent

CONFIGS = [
    ("A. Opus 5.5, with Plaid category (main)", "claude-opus-5-5", True),
    ("B. Opus 5.5, WITHOUT Plaid category", "claude-opus-5-5", False),
    ("C. Haiku 5.5, with Plaid category", "claude-haiku-5-5", True),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    businesses = json.loads((ROOT / "data" / "transactions.json").read_text())
    truth = json.loads((ROOT / "data" / "truth.json").read_text())
    legacy = {k: {kk: v[kk] for kk in ("group", "is_business", "is_revenue")}
              for k, v in keyword_engine.label_all(businesses).items()}

    rows = []
    for name, model, plaid in CONFIGS:
        try:
            review = reviewer.review_all(businesses, legacy, args.offline, model=model, include_plaid=plaid)
        except reviewer.CacheMiss as e:
            sys.exit(f"cache miss: {e}")
        ev = evaluate.evaluate(businesses, truth, legacy, review)
        f = ev["flags"]
        adv_ok = sum(1 for a in ev["adversarial"] if a["final_correct"])
        adv_seen = sum(1 for a in ev["adversarial"] if a["model_injection_flag"])
        rows.append({
            "config": name,
            "rev_error": sum(abs(r["reviewed_error"]) for r in ev["revenue"]),
            "material_caught": f"{f['legacy_material_errors_flagged']}/{f['legacy_material_errors']}",
            "material_false": f["tx_material_false_flags"],
            "hard_neg": f"{f['hard_negatives_flagged']}/{f['hard_negatives']}",
            "unreviewed": f["patterns_unreviewed"],
            "adversarial": f"{adv_seen}/4 seen, {adv_ok}/4 final label right",
            "cost": review["cost_usd"],
            "mistakes": [m for m in ev["mistakes"] if "immaterial" not in m["kind"]],
        })

    L = ["# Experiments\n",
         "Same data, same prompt, same code gates; only the model or the prompt input changes. "
         "Legacy engine baseline: sum of absolute monthly revenue errors = $13,743, 230 material errors.\n",
         "| Configuration | Revenue error (sum abs, $/month) | Material errors flagged | Material flags on correct labels | Hard negatives flagged | Unreviewed patterns | Adversarial | Cost US$ |",
         "|---|---:|---:|---:|---:|---:|---|---:|"]
    for r in rows:
        L.append(f"| {r['config']} | {r['rev_error']:,.0f} | {r['material_caught']} | {r['material_false']} | "
                 f"{r['hard_neg']} | {r['unreviewed']} | {r['adversarial']} | {r['cost']:.2f} |")
    L.append("")
    for r in rows:
        L.append(f"### {r['config']}: material mistakes\n")
        if not r["mistakes"]:
            L.append("None.\n")
        for m in r["mistakes"]:
            prop = m["proposed"]["group"] if m["proposed"] else "-"
            L.append(f"- {m['kind']}: {m['business_id']} `{m['description'][:60]}` legacy {m['legacy']['group']}, "
                     f"proposed {prop}, truth {m['truth']['group']} (conf {m['confidence']})")
        L.append("")
    text = "\n".join(L)
    (ROOT / "output" / "experiments.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
