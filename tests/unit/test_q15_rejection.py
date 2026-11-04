"""Q-15: 差戻し（rejected）の試験 R-1〜R-8 と、差戻しログ（1 ファイルに加筆）の試験。ダミー役割・費用 0。"""
import sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for d in ("orchestrator", "shared", "admin-ui"):
    sys.path.insert(0, str(ROOT / "src" / d))
import coo as coo_mod, task_engine as te, rejection_log as rl  # noqa: E402
from task_engine import Rejected  # noqa: E402

LIM = {"max_retries": 2, "max_runtime_seconds": 300, "consecutive_failures_to_stop_role": 3, "max_cost_usd": 0}
AP = {"ttl_hours": 24, "max_pending_high_risk": 5}


class R:
    def __init__(self, i): self.role_id, self.dept_code, self.impl_status = i, "T", "implemented"


ROLES = {k: R(k) for k in ("X", "Y")}
WF = {"wf": {"steps": [{"id": "A", "role": "X", "risk": "low"}, {"id": "B", "role": "Y", "risk": "low", "depends_on": ["A"]}]}}


class Clock:
    t = 1000.0
    def __call__(self): return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(); self.calls = {"X": 0, "Y": 0}; self.mode = "reject"
    def tearDown(self): self.d.cleanup()

    def coo(self):
        def x(p, u):
            self.calls["X"] += 1
            if self.mode == "reject": raise Rejected("検査で不合格", ["ひな形の○○", "対応表の△△"])
            if self.mode == "error": raise RuntimeError("想定外")
            return {"v": 1}, 0.0
        def y(p, u):
            self.calls["Y"] += 1; return {"v": 2}, 0.0
        return coo_mod.COO(self.d.name, dict(LIM), dict(ROLES), {"X": x, "Y": y}, WF, {"01"}, dict(AP), clock=Clock())

    def reg(self, c, pid="P-1"):
        c.register_project({"project_id": pid, "client_id": "C", "service_id": "01", "workflow": "wf", "payload": {}})


class TestRejected(Base):
    def test_r1_no_retry(self):
        c = self.coo(); self.reg(c); [c.tick() for _ in range(4)]
        t = c.engine.get(c.get_project("P-1")["steps"]["A"]["task_id"])
        self.assertEqual((t["status"], t["attempts"], self.calls["X"]), ("rejected", 1, 1))

    def test_r2_does_not_stop_the_role(self):
        c = self.coo()
        for i in range(5):                                           # 連続失敗の上限（3）を超える差戻し
            self.reg(c, f"P-{i}")
        [c.tick() for _ in range(3)]
        self.assertEqual(c.engine.stopped(), set())
        self.assertEqual(c.engine._read_json("連続失敗.json", {}).get("X", 0), 0)

    def test_r3_ordinary_errors_still_retry_and_stop(self):
        self.mode = "error"; c = self.coo()
        for i in range(3): self.reg(c, f"P-{i}")
        [c.tick() for _ in range(4)]
        self.assertIn("X", c.engine.stopped())                         # 従来どおり: 連続失敗 3 回で自動停止
        self.assertGreaterEqual(self.calls["X"], 3)
        self.assertTrue(any(t["attempts"] > 1 for t in c.engine.all_tasks()))   # 従来どおり: 再試行される

    def test_r4_downstream_blocked_and_project_attention(self):
        c = self.coo(); self.reg(c); [c.tick() for _ in range(3)]
        self.assertEqual(self.calls["Y"], 0)
        self.assertEqual(c.get_project("P-1")["status"], "attention")

    def test_r5_human_queue_once_with_fix_points(self):
        c = self.coo(); self.reg(c); [c.tick() for _ in range(4)]
        items = [i for i in c.humans.open_items() if "差戻し" in i["title"]]
        self.assertEqual(len(items), 1)
        self.assertIn("ひな形の○○", items[0]["detail"]); self.assertIn("自動では変更しません", items[0]["detail"])
        self.assertEqual(items[0]["risk"], "mid")                    # 優先度は通常（mid）

    def test_r6_reregister_with_new_id_runs_again(self):
        c = self.coo(); self.reg(c); [c.tick() for _ in range(3)]
        self.mode = "ok"; self.reg(c, "P-2"); [c.tick() for _ in range(3)]
        self.assertEqual(c.get_project("P-2")["status"], "done")
        self.assertEqual(c.get_project("P-1")["status"], "attention")  # 元の案件は触らない

    def test_r7_dashboard_label(self):
        import build_dashboard as bd
        self.assertEqual(bd.LABEL["rejected"], "差戻し")


class TestRejectionLog(Base):
    def test_single_file_newest_first_append_only(self):
        c = self.coo(); self.reg(c); self.reg(c, "P-2"); [c.tick() for _ in range(3)]
        p = c.rejection_log
        rl.append(p, "確認結果", "P-1.A", "社長: ひな形を直す", "ひな形の○○", "（変更前の複製を保存）", "社長", clock=Clock())
        rl.append(p, "変更の実施", "P-1.A", "ひな形の○○を修正", "○○を△△に", "旧版 FMT_v2.22 を戻す", "Claude", clock=Clock())
        rows = rl.rows(p)
        self.assertEqual([r.split("|")[2].strip() for r in rows], ["変更の実施", "確認結果", "差戻し", "差戻し"])   # 新しい順
        self.assertEqual(len(list(Path(self.d.name).glob("*差戻し*"))), 1)                                  # ファイルは 1 つだけ
        self.assertIn("元に戻す方法", p.read_text(encoding="utf-8"))

    def test_rejects_bad_kind_and_foreign_file(self):
        p = Path(self.d.name) / "x.md"
        with self.assertRaises(ValueError): rl.append(p, "不明", "r", "c")
        p.write_text("別の文書", encoding="utf-8")
        with self.assertRaises(ValueError): rl.append(p, "差戻し", "r", "c")
        self.assertEqual(p.read_text(encoding="utf-8"), "別の文書")      # 想定外のファイルは書き換えない


if __name__ == "__main__":
    unittest.main()
