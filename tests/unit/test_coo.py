"""2-6 AI COO v0 の試験（ダミー役割・LLM なし・費用ゼロ）。T2-01〜T2-12 のうち基盤側で確認できるもの。"""
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src" / "orchestrator"))
sys.path.insert(0, str(ROOT / "tests" / "step2-scenarios"))
import approval_queue as aq  # noqa: E402
import coo as coo_mod  # noqa: E402
import dummy_roles as dr  # noqa: E402
import task_engine as te  # noqa: E402

with open(ROOT / "tests" / "step2-scenarios" / "dummy_workflow.yaml", encoding="utf-8") as _f:
    WF = yaml.safe_load(_f)["workflows"]
LIM = {"max_retries": 2, "max_runtime_seconds": 300, "consecutive_failures_to_stop_role": 3, "max_cost_usd": 0}
AP = {"ttl_hours": 24, "max_pending_high_risk": 5}
PROJ = {"project_id": "P-001", "client_id": "C-0001", "service_id": "01", "workflow": "dummy-a-to-b", "payload": {"value": 1}}


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory(); self.clock = Clock()
        self.coo = self.make()
        self.queue = aq.ApprovalQueue(self._d.name, AP, clock=self.clock)       # 人間側の承認操作
    def tearDown(self): self._d.cleanup()

    def make(self, limits=None, ap=None, roles=None, handlers=None):
        return coo_mod.COO(self._d.name, limits or dict(LIM), roles or dict(dr.DUMMY_ROLES),
                           handlers or dict(dr.HANDLERS), WF, {"01", "02"}, ap or dict(AP), clock=self.clock)

    def result_b(self, c=None, pid="P-001"):
        c = c or self.coo
        return c.engine.get(c.get_project(pid)["steps"]["B"]["task_id"])


class TestFlow(Base):
    def test_t2_01_a_to_b_completes_without_manual_steps(self):
        self.coo.register_project(PROJ)
        rep = self.coo.tick()
        self.assertEqual(rep["projects"], {"done": 1})
        self.assertEqual(self.result_b()["result"], {"value": 20})              # (1+1)*10
        self.assertEqual(rep["cost_usd_total"], 0)

    def test_t2_02_no_duplicate_registration_or_run(self):
        self.coo.register_project(PROJ); self.coo.register_project(PROJ)
        self.coo.tick(); self.coo.tick(); self.coo.tick()
        self.assertEqual(len(self.coo.projects()), 1); self.assertEqual(len(self.coo.engine.all_tasks()), 2)
        self.assertEqual([t["attempts"] for t in self.coo.engine.all_tasks()], [1, 1])

    def test_validation_on_register(self):
        for bad in ({**PROJ, "client_id": ""}, {**PROJ, "service_id": "99"}, {**PROJ, "workflow": "none"}):
            with self.assertRaises(coo_mod.COOError): self.coo.register_project(bad)

    def test_dependency_order(self):
        self.coo.register_project(PROJ); self.coo.tick()
        a = self.coo.engine.get(self.coo.get_project("P-001")["steps"]["A"]["task_id"])
        b = self.result_b()
        self.assertLess(a["history"][-1]["at"], b["history"][-1]["at"] + 1)
        self.assertEqual(a["status"], te.SUCCEEDED)


class TestApproval(Base):
    def setUp(self):
        super().setUp(); self.coo.register_project({**PROJ, "workflow": "dummy-high-risk"})

    def test_t2_03_blocked_until_approved(self):
        rep = self.coo.tick()
        self.assertEqual(self.result_b()["status"], te.AWAITING)               # 承認前は実行されない
        self.assertEqual(rep["projects"], {"running": 1}); self.assertEqual(len(rep["awaiting_approval"]), 1)
        self.assertEqual(self.coo.tick()["projects"], {"running": 1})

    def test_t2_03_approved_runs(self):
        self.coo.tick()
        rec = self.coo.get_project("P-001")["steps"]["B"]
        self.queue.approve(rec["approval_id"], "社長", rec["approval_payload"])
        self.assertEqual(self.coo.tick()["projects"], {"done": 1})

    def test_t2_03_expired_or_changed_not_run(self):
        self.coo.tick()
        rec = self.coo.get_project("P-001")["steps"]["B"]
        self.queue.approve(rec["approval_id"], "社長", rec["approval_payload"])
        self.clock.t += 25 * 3600                                               # 期限切れ
        self.coo.tick(); self.assertEqual(self.result_b()["status"], te.AWAITING)

    def test_high_risk_request_reaches_human_queue(self):
        self.coo.tick()
        self.assertTrue(any("承認依頼" in i["title"] for i in self.coo.humans.open_items()))

    def test_fail_closed_if_human_queue_cap_unset(self):
        c = self.make(ap={"ttl_hours": 24, "max_pending_high_risk": None})
        with self.assertRaises(aq.ApprovalError): c.tick()
        self.assertEqual(len(c.engine.all_tasks()), 0)                          # 何も作られない


class TestExceptions(Base):
    def test_t2_04_retry_stops_and_queues_human(self):
        self.coo.register_project({**PROJ, "workflow": "dummy-failing"})
        rep = self.coo.tick()
        t = self.coo.engine.get(self.coo.get_project("P-001")["steps"]["A"]["task_id"])
        self.assertEqual((t["status"], t["attempts"]), (te.FAILED, 3))           # 無限ループしない
        self.assertEqual(self.result_b()["status"], te.BLOCKED)                  # 下流はブロック
        self.assertEqual(rep["projects"], {"attention": 1})
        titles = [i["title"] for i in self.coo.humans.open_items()]
        self.assertTrue(any("失敗" in x for x in titles))
        self.assertTrue(any("自動停止" in x for x in titles))                     # T2-08

    def test_t2_09_failure_log_and_rollback_proposal(self):
        self.coo.register_project({**PROJ, "workflow": "dummy-failing"}); self.coo.tick()
        item = next(i for i in self.coo.humans.open_items() if "失敗" in i["title"])
        self.assertIn("障害ログ", item["detail"]); self.assertIn("切り戻し案", item["detail"])

    def test_no_duplicate_escalation(self):
        self.coo.register_project({**PROJ, "workflow": "dummy-failing"}); self.coo.tick()
        n = len(self.coo.humans.open_items()); self.coo.tick(); self.coo.tick()
        self.assertEqual(len(self.coo.humans.open_items()), n)

    def test_t2_08_circuit_breaker_stops_role(self):
        self.coo.register_project({**PROJ, "workflow": "dummy-failing"}); self.coo.tick()
        self.assertIn("DUMMY-FAIL", self.coo.engine.stopped())

    def test_unimplemented_role_blocked_with_human_notice(self):
        wf = {"x": {"steps": [{"id": "A", "role": "DUMMY-NOTREADY"}]}}
        c = coo_mod.COO(self._d.name, dict(LIM), dict(dr.DUMMY_ROLES), dict(dr.HANDLERS), wf, {"01"}, dict(AP), clock=self.clock)
        c.register_project({**PROJ, "workflow": "x"}); c.tick()
        self.assertEqual(c.engine.all_tasks()[0]["status"], te.BLOCKED)
        self.assertTrue(any("割当不可" in i["title"] for i in c.humans.open_items()))


class TestGuards(Base):
    def test_t2_05_cost_stops_and_logs(self):
        h = dict(dr.HANDLERS); h["DUMMY-A"] = lambda p, u: ({"value": 1}, 0.5)
        c = self.make(handlers=h)                                               # max_cost_usd=0 → 費用が出たら停止
        c.register_project(PROJ); c.tick()
        self.assertIn("DUMMY-A", c.engine.stopped())
        self.assertEqual(c.engine.stop_log()[-1]["event"], "auto_stop")

    def test_t2_06_limits_unset_does_not_start(self):
        c = self.make(limits={**LIM, "max_retries": None})
        c.register_project(PROJ)
        with self.assertRaises(te.EngineError): c.tick()
        self.assertTrue(all(t["attempts"] == 0 for t in c.engine.all_tasks()))

    def test_t2_07_stop_and_only_human_resumes(self):
        self.coo.engine.stop("all", actor="社長", reason="緊急")
        self.coo.register_project(PROJ)
        self.assertEqual(self.coo.tick()["projects"], {"running": 1})            # 停止中は進まない
        self.assertFalse(hasattr(self.coo, "resume"))                             # COO は再開手段を持たない
        self.coo.engine.resume("all", actor="社長")
        self.assertEqual(self.coo.tick()["projects"], {"done": 1})
        self.coo.engine.stop("DUMMY", actor="社長")                               # 部コード単位の停止
        self.coo.register_project({**PROJ, "project_id": "P-002"})
        self.assertEqual(self.coo.tick()["projects"], {"done": 1, "running": 1})   # P-002 は進まない
        self.coo.engine.stop("DUMMY-B", actor="社長", reason="役割単位")
        self.assertIn("DUMMY-B", self.coo.engine.stopped())

    def test_t2_11_new_dummy_role_needs_no_core_change(self):
        roles = dict(dr.DUMMY_ROLES); roles["DUMMY-C"] = dr.DummyRole("DUMMY-C")
        handlers = dict(dr.HANDLERS); handlers["DUMMY-C"] = lambda p, u: ({"value": 99}, 0.0)
        wf = {"w": {"steps": [{"id": "A", "role": "DUMMY-C"}]}}
        c = coo_mod.COO(self._d.name, dict(LIM), roles, handlers, wf, {"01"}, dict(AP), clock=self.clock)
        c.register_project({**PROJ, "workflow": "w"})
        self.assertEqual(c.tick()["projects"], {"done": 1})

    def test_t2_12_coo_cannot_write_approvals_or_resume(self):
        for name in ("approve", "reject", "resume", "consume"):
            self.assertFalse(hasattr(self.coo.approvals, name)); self.assertFalse(hasattr(self.coo, name))
        self.coo.register_project({**PROJ, "workflow": "dummy-high-risk"}); self.coo.tick()
        self.assertEqual(self.result_b()["status"], te.AWAITING)                 # COO 自身では進められない
        self.assertTrue(all(h["actor"] in ("AI-000",) for h in self.queue.history() if h["event"] == "requested"))


class TestRealRegistry(Base):
    def test_real_ledger_roles_not_implemented_are_not_assigned(self):
        """台帳の実役割は未実装のため、割り当てられない（実装対象はダミーのみ。Q-05）。"""
        sys.path.insert(0, str(ROOT / "src" / "shared"))
        import role_registry as rr
        roles, errs, _ = rr.validate(ROOT); self.assertEqual(errs, [])
        wf = {"w": {"steps": [{"id": "A", "role": "AI-000"}]}}
        c = coo_mod.COO(self._d.name, dict(LIM), {r.role_id: r for r in roles}, {}, wf, {"01"}, dict(AP), clock=self.clock)
        c.register_project({**PROJ, "workflow": "w"}); c.tick()
        self.assertEqual(c.engine.all_tasks()[0]["status"], te.BLOCKED)


if __name__ == "__main__":
    unittest.main()
