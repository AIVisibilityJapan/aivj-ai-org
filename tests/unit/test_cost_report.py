"""2-8 費用・実行ログの集計の試験。"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src" / "orchestrator"))
sys.path.insert(0, str(ROOT / "src" / "shared"))
sys.path.insert(0, str(ROOT / "src" / "admin-ui"))
import build_dashboard as bd  # noqa: E402
import cost_report as cr  # noqa: E402
import task_engine as te  # noqa: E402

LIM = {"max_retries": 2, "max_runtime_seconds": 300, "consecutive_failures_to_stop_role": 3, "max_cost_usd": 10}
DAY = 1762210800.0  # 2025-11-04 08:20 JST 相当の固定時刻


class Costs(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.d = Path(self._t.name)
        self.now = DAY
        self.eng = te.TaskEngine(self.d, LIM, clock=lambda: self.now)

    def tearDown(self):
        self._t.cleanup()

    def spend(self, key, role, usd):
        self.eng.submit(key, role)
        t = self.eng.claim("w")
        self.eng.record_cost(t["task_id"], "w", usd)
        self.eng.complete(t["task_id"], "w")

    def test_by_day_role_project(self):
        self.spend("P-1.a", "AI-A", 1.5)
        self.now += 86400
        self.spend("P-1.b", "AI-B", 0.5)
        self.spend("P-2.a", "AI-A", 2.0)
        s = cr.summarize(self.eng.all_tasks())
        self.assertEqual(s["total"], 4.0)
        self.assertEqual(s["by_role"], {"AI-A": 3.5, "AI-B": 0.5})
        self.assertEqual(s["by_project"], {"P-1": 2.0, "P-2": 2.0})
        self.assertEqual(sorted(s["by_day"].values()), [1.5, 2.5])

    def test_total_matches_engine(self):
        self.spend("P-1.a", "AI-A", 1.25)
        self.spend("P-1.b", "AI-A", 0.75)
        self.assertEqual(cr.summarize(self.eng.all_tasks())["total"], self.eng.total_cost())

    def test_yen_shown_next_to_usd(self):
        self.assertEqual(cr.fmt_money(2.0, 157), "$2.00（約 314 円）")
        self.assertEqual(cr.fmt_money(0, 157), "$0.00（約 0 円）")

    def test_no_rate_means_usd_only(self):
        self.assertEqual(cr.fmt_money(2.0, None), "$2.00")
        for bad in (0, -1, True, "157", None):
            p = self.d / "b.yaml"
            p.write_text(f"display:\n  usd_jpy: {bad!r}\n" if bad is not None else "display:\n  usd_jpy: null\n", encoding="utf-8")
            self.assertIsNone(cr.load_rate(p)[0], bad)
        self.assertIsNone(cr.load_rate(self.d / "none.yaml")[0])

    def test_rate_from_real_settings(self):
        r, day = cr.load_rate(ROOT / "設定" / "budgets.yaml")
        self.assertEqual(r, 157.0)
        self.assertTrue(day)

    def test_dashboard_shows_usd_and_yen(self):
        self.spend("P-1.a", "AI-A", 2.0)
        p = bd.render(bd.collect(self.d, ROOT / "設定" / "budgets.yaml"))
        self.assertIn("$2.00（約 314 円）", p)
        self.assertIn("費用の集計", p)
        self.assertIn("上限の判定には使いません", p)

    def test_dashboard_without_rate_has_no_yen(self):
        self.spend("P-1.a", "AI-A", 2.0)
        p = bd.render(bd.collect(self.d, self.d / "none.yaml"))
        self.assertNotIn("円）", p)
        self.assertIn("為替が未設定", p)

    def test_csv(self):
        self.spend("P-1.a", "AI-A", 2.0)
        c = cr.to_csv(cr.summarize(self.eng.all_tasks()), 157)
        self.assertIn("役割別,AI-A,2.0,314", c)
        self.assertIn("合計,,2.0,314", c)
        out = cr.write_csv(cr.summarize(self.eng.all_tasks()), None, self.d / "x.csv")
        self.assertTrue(out.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_bad_cost_data_ignored(self):
        t = {"task_id": "T-1", "role_id": "R", "idempotency_key": "P.a", "cost_usd": "abc", "history": [{"event": "cost", "at": "x", "detail": "?"}]}
        self.assertEqual(cr.summarize([t])["total"], 0)


if __name__ == "__main__":
    unittest.main()
