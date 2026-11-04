"""2-7 管理画面の試験。表示専用・外部に出ない・内容を出さない・読めないデータを隠さない。"""
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src" / "orchestrator"))
sys.path.insert(0, str(ROOT / "src" / "admin-ui"))
import approval_queue as aq  # noqa: E402
import build_dashboard as bd  # noqa: E402
import task_engine as te  # noqa: E402

LIM = {"max_retries": 2, "max_runtime_seconds": 300, "consecutive_failures_to_stop_role": 3, "max_cost_usd": 0}
SECRET = "顧客秘密ABC123"


class AdminUi(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.d = Path(self._t.name)
        self.eng = te.TaskEngine(self.d, LIM)
        self.aq = aq.ApprovalQueue(self.d, {"ttl_hours": 24})
        self.hq = aq.HumanQueue(self.d, {"max_pending_high_risk": 5})

    def tearDown(self):
        self._t.cleanup()

    def page(self):
        return bd.render(bd.collect(self.d, ROOT / "設定" / "budgets.yaml"))

    def test_empty_state_renders(self):
        p = self.page()
        self.assertIn("AIVJ 管理画面", p)
        self.assertIn("未設定（起動しない）", p)

    def test_no_script_no_external_no_links(self):
        p = self.page()
        for bad in ("<script", "<a ", "http://", "https://", "<form", "<iframe", "onclick"):
            self.assertNotIn(bad, p)
        self.assertIn("default-src 'none'", p)

    def test_payload_result_detail_not_shown(self):
        t = self.eng.submit("P-1.s1", "AI-X", payload={"memo": SECRET})
        self.aq.request("send", "high", {"memo": SECRET}, "AI-X", summary="概要のみ")
        self.hq.add("社長", "確認", "low", detail=SECRET)
        self.eng.claim("w"); self.eng.complete(t["task_id"], "w", result={"r": SECRET})
        self.assertNotIn(SECRET, self.page())
        self.assertIn("概要のみ", self.page())

    def test_html_is_escaped(self):
        self.aq.request("x", "low", {}, "AI-X", summary="<img src=x onerror=alert(1)>")
        p = self.page()
        self.assertNotIn("<img", p)
        self.assertIn("&lt;img", p)

    def test_stop_and_pending_shown(self):
        self.eng.stop("all", actor="社長", reason="試験")
        self.aq.request("send", "mid", {"a": 1}, "AI-X", summary="s")
        p = self.page()
        self.assertIn("停止中: all", p)
        self.assertIn("試験", p)
        self.assertIn("send", p)

    def test_unreadable_data_is_visible(self):
        self.eng.submit("P-1.s1", "AI-X")
        (self.d / "tasks" / "T-bad.json").write_text("{壊れている", encoding="utf-8")
        (self.d / "停止ログ.jsonl").write_text("not json\n", encoding="utf-8")
        p = self.page()
        self.assertIn("読めないデータがあります", p)
        self.assertIn("T-bad.json", p)

    def test_read_only_state_unchanged(self):
        self.eng.submit("P-1.s1", "AI-X")
        self.eng.stop("D07", reason="r")
        before = {p: p.read_bytes() for p in self.d.rglob("*") if p.is_file()}
        out = self.d.parent / "dash_out.html"
        bd.build(self.d, out, ROOT / "設定" / "budgets.yaml")
        after = {p: p.read_bytes() for p in self.d.rglob("*") if p.is_file()}
        out.unlink()
        self.assertEqual(before, after)

    def test_projects_grouped_and_overdue(self):
        self.eng.submit("P-1.a", "AI-X"); self.eng.submit("P-1.b", "AI-X"); self.eng.submit("P-2.a", "AI-X")
        self.hq.add("社長", "期限切れ", "low", due=1.0)
        d = bd.collect(self.d, ROOT / "設定" / "budgets.yaml")
        self.assertEqual(sorted(d["projects"]), ["P-1", "P-2"])
        self.assertEqual(len(d["overdue"]), 1)
        self.assertIn("期限超過", bd.render(d))

    def test_missing_budgets_shows_unknown(self):
        p = bd.render(bd.collect(self.d, self.d / "nonexistent.yaml"))
        self.assertIn("不明", p)

    def test_no_state_dir_does_not_crash(self):
        p = bd.render(bd.collect(self.d / "none", ROOT / "設定" / "budgets.yaml"))
        self.assertIn("AIVJ 管理画面", p)


if __name__ == "__main__":
    unittest.main()
