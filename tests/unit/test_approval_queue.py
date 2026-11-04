"""2-5 承認キュー・人間キューの試験。STEP 3 の T3-09・T3-10・T3-13 の自動確認を含む。"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src" / "orchestrator"))
import approval_queue as aq  # noqa: E402
import task_engine as te  # noqa: E402

LIM = {"ttl_hours": 24, "max_pending_high_risk": 2}
ENG = {"max_retries": 2, "max_runtime_seconds": 300, "consecutive_failures_to_stop_role": 5, "max_cost_usd": 0}
P = {"role": "TEST-01", "yaml": "a: 1"}


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory(); self.clock = Clock()
        self.q = aq.ApprovalQueue(self._d.name, dict(LIM), clock=self.clock)
        self.h = aq.HumanQueue(self._d.name, dict(LIM), clock=self.clock)
    def tearDown(self): self._d.cleanup()


class TestApproval(Base):
    def req(self): return self.q.request("AI 社員の本番反映", "low", P, "AI-07-01")

    def test_approve_then_verify_and_consume_once(self):
        a = self.req(); self.q.approve(a["approval_id"], "社長", P)
        self.assertTrue(self.q.verify(a["approval_id"], P)[0])
        self.q.consume(a["approval_id"], P)
        with self.assertRaises(aq.ApprovalError): self.q.consume(a["approval_id"], P)    # 再利用不可

    def test_t3_09_content_change_after_approval_invalidates(self):
        a = self.req(); self.q.approve(a["approval_id"], "社長", P)
        changed = {**P, "yaml": "a: 2"}
        ok, why = self.q.verify(a["approval_id"], changed)
        self.assertFalse(ok); self.assertIn("ハッシュ不一致", why)
        with self.assertRaises(aq.ApprovalError): self.q.consume(a["approval_id"], changed)
        self.assertTrue(any(h["event"] == "denied_use" for h in self.q.history()))

    def test_approve_with_different_content_refused(self):
        a = self.req()
        with self.assertRaises(aq.ApprovalError): self.q.approve(a["approval_id"], "社長", {**P, "yaml": "x"})

    def test_t3_10_unapproved_not_usable(self):
        a = self.req()
        self.assertFalse(self.q.verify(a["approval_id"], P)[0])
        with self.assertRaises(aq.ApprovalError): self.q.consume(a["approval_id"], P)

    def test_ai_cannot_approve_or_reject(self):
        a = self.req()
        for who in ("AI-000", "AI-07-01", "TEST-01", "", "業務委託者"):
            with self.assertRaises(aq.ApprovalError): self.q.approve(a["approval_id"], who, P)
            with self.assertRaises(aq.ApprovalError): self.q.reject(a["approval_id"], who, "理由")

    def test_t3_13_reject_requires_reason_and_blocks(self):
        a = self.req()
        with self.assertRaises(aq.ApprovalError): self.q.reject(a["approval_id"], "社長", " ")
        self.q.reject(a["approval_id"], "社長", "定義案の権限が広い")
        self.assertFalse(self.q.verify(a["approval_id"], P)[0])
        self.assertEqual(self.q.history()[-1]["note"], "定義案の権限が広い")

    def test_expiry(self):
        a = self.req(); self.q.approve(a["approval_id"], "社長", P)
        self.clock.t += 24 * 3600 + 1
        self.assertEqual(self.q.verify(a["approval_id"], P), (False, "有効期限切れ"))

    def test_ttl_unset_fails_closed(self):
        q = aq.ApprovalQueue(self._d.name, {"ttl_hours": None}, clock=self.clock)
        a = q.request("x", "low", P, "AI-000")
        with self.assertRaises(aq.ApprovalError): q.approve(a["approval_id"], "社長", P)

    def test_cannot_decide_twice(self):
        a = self.req(); self.q.approve(a["approval_id"], "社長", P)
        with self.assertRaises(aq.ApprovalError): self.q.reject(a["approval_id"], "社長", "後から")

    def test_hash_is_order_independent(self):
        self.assertEqual(aq.payload_hash({"a": 1, "b": 2}), aq.payload_hash({"b": 2, "a": 1}))

    def test_history_is_append_only_and_complete(self):
        a = self.req(); self.q.approve(a["approval_id"], "社長", P); self.q.consume(a["approval_id"], P)
        self.assertEqual([h["event"] for h in self.q.history()], ["requested", "approved", "used"])

    def test_release_task_only_with_valid_approval(self):
        eng = te.TaskEngine(self._d.name, dict(ENG), clock=self.clock)
        t = eng.submit("K1", "TEST-01", requires_approval=True)
        a = self.req()
        with self.assertRaises(aq.ApprovalError): self.q.release_task(eng, t["task_id"], a["approval_id"], P)  # 未承認
        self.assertIsNone(eng.claim("w"))
        self.q.approve(a["approval_id"], "社長", P)
        self.q.release_task(eng, t["task_id"], a["approval_id"], P)
        self.assertIsNotNone(eng.claim("w"))

    def test_sample_with_real_step3_files(self):
        """承認依頼書のハッシュの付け方: ファイルのバイト列そのもの。"""
        f = ROOT / "文書" / "手順書" / "STEP3_試験役割_定義案.yaml"
        a = self.q.request("AI 社員の本番反映", "low", f.read_bytes(), "AI-07-01")
        self.q.approve(a["approval_id"], "社長", f.read_bytes())
        self.assertTrue(self.q.verify(a["approval_id"], f.read_bytes())[0])


class TestHumanQueue(Base):
    def test_add_and_done_with_notification_pending(self):
        i = self.h.add("社長", "STEP3 申請書類の確認", "low", due=2000)
        self.assertEqual(len(self.h.open_items()), 1)
        n = (Path(self._d.name) / "通知送信待ち.jsonl").read_text(encoding="utf-8")
        self.assertIn('"sent": false', n); self.assertIn("Gmail", n)   # 送信はしない
        self.h.done(i["item_id"], "社長"); self.assertEqual(self.h.open_items(), [])

    def test_high_risk_cap_fail_closed_and_limit(self):
        h0 = aq.HumanQueue(self._d.name, {"max_pending_high_risk": None}, clock=self.clock)
        with self.assertRaises(aq.ApprovalError): h0.add("社長", "x", "high")
        self.h.add("社長", "a", "high"); self.h.add("社長", "b", "high")
        with self.assertRaises(aq.ApprovalError): self.h.add("社長", "c", "high")
        self.h.add("社長", "d", "low")                               # 低リスクは上限の対象外

    def test_overdue(self):
        self.h.add("業務委託者", "x", "low", due=1500)
        self.assertEqual(self.h.overdue(), []); self.clock.t = 1600
        self.assertEqual(len(self.h.overdue()), 1)


if __name__ == "__main__":
    unittest.main()
