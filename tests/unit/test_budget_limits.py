"""D-035 上限の設定値。設定ファイルから読み込んだ値で、基盤が起動・承認できる（かつ費用は 0 のまま）。"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src" / "shared"))
sys.path.insert(0, str(ROOT / "src" / "orchestrator"))
import approval_queue as aq  # noqa: E402
import budget_limits as bl  # noqa: E402
import task_engine as te  # noqa: E402


class Limits(unittest.TestCase):
    def test_values_as_approved(self):
        d = bl.load()
        self.assertEqual(d["engine"], {"max_retries": 2, "max_runtime_seconds": 600, "consecutive_failures_to_stop_role": 3, "max_cost_usd": 0})
        self.assertEqual(d["approval"], {"ttl_hours": 24, "max_pending_high_risk": 5})
        self.assertEqual(d["daily_max_cost_usd"], 0)

    def test_engine_starts_and_any_cost_stops_the_role(self):
        d = bl.load()
        with tempfile.TemporaryDirectory() as t:
            eng = te.TaskEngine(t, d["engine"])
            eng.submit("P-1.a", "AI-X")
            task = eng.claim("w")
            self.assertIsNotNone(task)                                   # 上限が入ったので起動できる
            eng.record_cost(task["task_id"], "w", 0.01)                   # 費用 0 の上限 → 少しでも発生したら止まる
            self.assertIn("AI-X", eng.stopped())

    def test_approval_works_with_ttl(self):
        d = bl.load()
        with tempfile.TemporaryDirectory() as t:
            q = aq.ApprovalQueue(t, d["approval"])
            a = q.request("x", "low", {"a": 1}, "AI-X")
            self.assertEqual(q.approve(a["approval_id"], "社長", {"a": 1})["status"], "approved")

    def test_unset_or_bad_values_stay_none(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "b.yaml"
            p.write_text("per_run_limits:\n  max_retries: null\n  max_runtime_seconds: -1\n  max_cost_usd: true\napproval:\n  ttl_hours: abc\n", encoding="utf-8")
            d = bl.load(p)
            self.assertEqual(d["engine"], {"max_retries": None, "max_runtime_seconds": None, "consecutive_failures_to_stop_role": None, "max_cost_usd": None})
            self.assertIsNone(d["approval"]["ttl_hours"])


if __name__ == "__main__":
    unittest.main()
