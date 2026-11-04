"""2-3 タスクエンジンの試験。実行: python -m unittest discover -s tests/unit -v"""
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src" / "orchestrator"))
sys.path.insert(0, str(ROOT / "src" / "shared"))
import task_engine as te  # noqa: E402
import role_registry as rr  # noqa: E402

OK = {"max_retries": 2, "max_runtime_seconds": 300}


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.eng = te.TaskEngine(self._tmp.name, dict(OK), clock=self.clock)
    def tearDown(self): self._tmp.cleanup()


class TestEngine(Base):
    def test_idempotent_submit(self):
        a = self.eng.submit("K1", "AI-000"); b = self.eng.submit("K1", "AI-000")
        self.assertEqual(a["task_id"], b["task_id"]); self.assertEqual(len(self.eng.all_tasks()), 1)

    def test_claim_and_complete(self):
        self.eng.submit("K1", "AI-000")
        t = self.eng.claim("w1"); self.assertEqual(t["status"], te.RUNNING); self.assertEqual(t["attempts"], 1)
        self.assertIsNone(self.eng.claim("w2"))                      # 実行中は取れない
        done = self.eng.complete(t["task_id"], "w1", {"ok": 1})
        self.assertEqual(done["status"], te.SUCCEEDED)

    def test_no_double_execution_threads(self):
        for i in range(5): self.eng.submit(f"K{i}", "AI-000")
        got, lock = [], threading.Lock()
        def work():
            while True:
                t = self.eng.claim(threading.current_thread().name)
                if t is None: return
                with lock: got.append(t["task_id"])
        ths = [threading.Thread(target=work, name=f"w{i}") for i in range(4)]
        [x.start() for x in ths]; [x.join() for x in ths]
        self.assertEqual(len(got), 5); self.assertEqual(len(set(got)), 5)   # 重複なし・欠落なし

    def test_retry_then_fail_at_limit(self):
        self.eng.submit("K1", "AI-000")
        for n in range(1, 4):
            t = self.eng.claim("w"); self.assertEqual(t["attempts"], n)
            r = self.eng.fail(t["task_id"], "w", "テスト失敗")
            self.assertEqual(r["status"], te.QUEUED if n <= 2 else te.FAILED)
        self.assertIsNone(self.eng.claim("w"))                       # 上限超過後は再取得されない

    def test_fail_closed_when_limits_unset(self):
        for lim in ({"max_retries": None, "max_runtime_seconds": 300},
                    {"max_retries": 2, "max_runtime_seconds": None}, {}, {"max_retries": True, "max_runtime_seconds": 5}):
            e = te.TaskEngine(self._tmp.name, lim, clock=self.clock)
            with self.assertRaises(te.EngineError): e.claim("w")

    def test_stop_and_resume(self):
        self.eng.submit("K1", "AI-000"); self.eng.stop("AI-000")
        self.assertIsNone(self.eng.claim("w"))
        self.eng.resume("AI-000"); self.assertIsNotNone(self.eng.claim("w"))
        self.eng.stop("all")
        self.eng.submit("K2", "AI-000"); self.assertIsNone(self.eng.claim("w2"))

    def test_approval_gate(self):
        t = self.eng.submit("K1", "AI-000", requires_approval=True)
        self.assertEqual(t["status"], te.AWAITING); self.assertIsNone(self.eng.claim("w"))
        self.eng.approve(t["task_id"], "社長"); self.assertIsNotNone(self.eng.claim("w"))
        with self.assertRaises(te.EngineError): self.eng.approve(t["task_id"], "社長")

    def test_lease_expiry_reaps(self):
        t = self.eng.submit("K1", "AI-000"); self.eng.claim("w")
        self.clock.t += 301
        self.assertEqual(self.eng.reap_expired(), [t["task_id"]])
        self.assertEqual(self.eng.get(t["task_id"])["status"], te.QUEUED)

    def test_wrong_worker_cannot_complete(self):
        t = self.eng.submit("K1", "AI-000"); self.eng.claim("w1")
        with self.assertRaises(te.EngineError): self.eng.complete(t["task_id"], "w2")

    def test_unsafe_identifier_rejected(self):
        with self.assertRaises(te.EngineError): self.eng.submit("../x", "AI-000")


class TestWithRegistry(Base):
    def test_only_implemented_roles_assigned(self):
        roles, errs, _ = rr.validate(ROOT)
        self.assertEqual(errs, [])
        eng = te.TaskEngine(self._tmp.name, dict(OK), roles={r.role_id: r for r in roles}, clock=self.clock)
        eng.submit("K1", "AI-000")              # 台帳上は definition_drafted → 割当不可
        eng.submit("K2", "AI-9999")             # 台帳にない
        self.assertIsNone(eng.claim("w"))


if __name__ == "__main__":
    unittest.main()
