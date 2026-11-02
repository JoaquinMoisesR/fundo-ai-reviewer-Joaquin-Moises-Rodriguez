"""Fast checks on the parts that must never silently break. Run: python -m unittest -v"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import credit_impact  # noqa: E402
import keyword_engine  # noqa: E402
import reviewer  # noqa: E402
from taxonomy import is_revenue  # noqa: E402


def tx(name, amount, tid="t1", date="2025-01-02"):
    return {"transaction_id": tid, "name": name, "amount": amount, "date": date,
            "personal_finance_category": {"detailed": "X"}}


class Taxonomy(unittest.TestCase):
    def test_plaid_sign_convention(self):
        self.assertTrue(is_revenue(-100, True, "none"))       # negative = money IN
        self.assertFalse(is_revenue(100, True, "none"))       # positive = money OUT
        self.assertFalse(is_revenue(-100, False, "none"))     # personal
        self.assertFalse(is_revenue(-100, True, "active_advance"))


class KeywordEngine(unittest.TestCase):
    def test_transfer_is_not_nsf(self):  # regression: TRA-NSF-ER
        self.assertNotEqual(keyword_engine.label(tx("STRIPE TRANSFER ST-1", -500))["group"], "nsf")

    def test_punctuation_keyword_never_matches(self):  # deliberate legacy flaw
        self.assertEqual(keyword_engine.label(tx("ORIG CO NAME:KABBAGE ENTRY DESCR:LOAN PMT", 180))["group"], "none")

    def test_square_capital_looks_like_sales(self):  # deliberate legacy flaw
        lab = keyword_engine.label(tx("SQUARE CAPITAL LOAN PROCEEDS 1", -12000))
        self.assertEqual(lab["group"], "auto_deposit")
        self.assertTrue(lab["is_revenue"])


class Validation(unittest.TestCase):
    P = [{"id": "p000"}, {"id": "p001"}]

    def good(self, **kw):
        r = {"id": "p000", "agree": True, "group": "none", "is_business": True,
             "confidence": 0.9, "reason": "", "injection_suspected": False}
        return r | kw

    def test_garbage_is_rejected(self):
        out, problems = reviewer.validate("not json", self.P)
        self.assertEqual(out, {})
        self.assertTrue(problems)

    def test_bad_items_dropped(self):
        raw = json.dumps({"reviews": [self.good(), self.good(id="p999"), self.good(id="p001", group="revenue"),
                                      self.good(id="p001", confidence=7)]})
        out, problems = reviewer.validate(raw, self.P)
        self.assertEqual(set(out), {"p000"})
        self.assertGreaterEqual(len(problems), 3)


class Offer(unittest.TestCase):
    def test_rule(self):
        self.assertAlmostEqual(credit_impact.offer(10000, 100, 0), 10000)  # 12000 - 2000
        self.assertEqual(credit_impact.offer(10000, 100, 6), 0.0)          # NSF cut-off
        self.assertEqual(credit_impact.offer(1000, 500, 0), 0.0)           # floored at 0


class Reproducibility(unittest.TestCase):
    def test_offline_replay_matches_committed_report(self):
        """The committed cache must reproduce every pattern without a key."""
        data = ROOT / "data"
        businesses = json.loads((data / "transactions.json").read_text())
        legacy = keyword_engine.label_all(businesses)
        review = reviewer.review_all(businesses, legacy, offline=True)
        self.assertEqual(sum(1 for r in review["results"] if r["status"] != "ok"), 0)
        unreviewed = [p for r in review["results"] for p in r["patterns"] if p["status"] != "reviewed"]
        self.assertEqual(unreviewed, [])


class InputFormats(unittest.TestCase):
    def test_plaid_response_shape_is_grouped_by_account(self):
        import tempfile
        import run
        raw = {"transactions": [
            {"account_id": "a1", "date": "2025-01-02", "amount": -10, "name": "X"},
            {"account_id": "a2", "date": "2025-01-03", "amount": 5, "name": "Y"},
            {"account_id": "a1", "date": "2025-01-01", "amount": 7, "name": "Z"}]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(raw, f)
        bs = run.load_input(Path(f.name))
        self.assertEqual(sorted(b["business_id"] for b in bs), ["a1", "a2"])
        a1 = next(b for b in bs if b["business_id"] == "a1")
        self.assertEqual([t["date"] for t in a1["transactions"]], ["2025-01-01", "2025-01-02"])  # sorted
        self.assertTrue(all("transaction_id" in t for t in a1["transactions"]))

    def test_sample_input_replays_offline(self):
        import run
        bs = run.load_input(ROOT / "examples" / "sample_input.json")
        legacy = keyword_engine.label_all(bs)
        review = reviewer.review_all(bs, legacy, offline=True)
        self.assertEqual(review["results"][0]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
