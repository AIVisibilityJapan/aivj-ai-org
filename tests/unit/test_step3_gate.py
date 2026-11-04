"""STEP 3 の検査（T3-01, 03, 04, 05, 07, 09, 10, 11, 13, 14）。ダミー・試験用の要件と定義案のみ。"""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src" / "shared"))
sys.path.insert(0, str(ROOT / "src" / "orchestrator"))
import approval_queue as aq  # noqa: E402
import definition_gate as dg  # noqa: E402

REQ = (ROOT / "文書" / "手順書" / "STEP3_試験題材.md").read_text(encoding="utf-8")
DEF_PATH = ROOT / "文書" / "手順書" / "STEP3_試験役割_定義案.yaml"
DEF = yaml.safe_load(DEF_PATH.read_text(encoding="utf-8"))
CODE = ROOT / "tests" / "step3-sandbox" / "site_check" / "check.py"


def variant(**kw):
    d = copy.deepcopy(DEF)
    for path, v in kw.items():
        cur = d
        keys = path.split("__")
        for k in keys[:-1]:
            cur = cur[k]
        cur[keys[-1]] = v
    return d


class Requirements(unittest.TestCase):
    def test_t3_01_example_is_complete(self):
        self.assertTrue(dg.check_requirements(REQ)["ok"], dg.check_requirements(REQ)["missing"])

    def test_t3_01_blank_template_lists_missing_and_stops(self):
        tpl = (ROOT / "テンプレート" / "業務要件_仮様式.md").read_text(encoding="utf-8")
        r = dg.check_requirements(tpl)
        self.assertFalse(r["ok"])
        for k in ("役割の名称", "目的", "禁止事項", "リスク段階", "合格の基準"):
            self.assertIn(k, r["missing"])

    def test_t3_01_one_item_missing(self):
        text = REQ.replace("- 禁止: 外部への送信、ネットワークアクセス、費用の発生、本番フォルダの変更", "- 禁止:")
        r = dg.check_requirements(text)
        self.assertEqual(r["missing"], ["禁止事項"])
        with self.assertRaises(ValueError):                                   # 先へ進まない
            dg.build_approval_request(aq.ApprovalQueue(tempfile.mkdtemp(), {"ttl_hours": 1}), text, DEF, [DEF_PATH])


class Definition(unittest.TestCase):
    def test_real_definition_passes(self):
        r = dg.check_definition(REQ, DEF)
        self.assertTrue(r["ok"], r["violations"])
        self.assertFalse(r["needs_cost_confirmation"])
        self.assertTrue(dg.may_run(r))

    def test_t3_03_forbidden_grants_detected(self):
        for field, extra in (("tools", "メールの送信"), ("tools", "ネットワークアクセス"), ("permissions", "write: 本番フォルダ"),
                             ("permissions", "有料 API の呼び出し")):
            d = variant()
            d["definition"][field] = list(d["definition"][field]) + [extra]
            r = dg.check_definition(REQ, d)
            self.assertFalse(r["ok"], extra)
            self.assertTrue(any("禁止されている権限" in v for v in r["violations"]), (extra, r["violations"]))

    def test_t3_03_missing_carry_over_of_prohibition(self):
        d = variant()
        d["definition"]["permissions"] = [p for p in d["definition"]["permissions"] if not p.startswith("禁止")]
        d["definition"]["forbidden"] = []
        r = dg.check_definition(REQ, d)
        self.assertFalse(r["ok"])
        self.assertTrue(any("引き継がれていない" in v for v in r["violations"]))

    def test_t3_03_no_approval_request_when_violating(self):
        d = variant()
        d["definition"]["tools"] = list(d["definition"]["tools"]) + ["外部への送信"]
        q = aq.ApprovalQueue(tempfile.mkdtemp(), {"ttl_hours": 1})
        with self.assertRaises(ValueError):
            dg.build_approval_request(q, REQ, d, [DEF_PATH])
        self.assertEqual(q.pending(), [])

    def test_t3_04_higher_risk_rejected(self):
        for tier in ("mid", "high"):
            r = dg.check_definition(REQ, variant(max_risk_tier=tier))
            self.assertFalse(r["ok"])
            self.assertTrue(any("より高い" in v for v in r["violations"]))
        self.assertIsNotNone(dg.RISK_ORDER["low"])

    def test_t3_07_cost_requires_president_confirmation(self):
        r = dg.check_definition(REQ.replace("、費用の発生", ""), variant(definition__limits={"max_retries": 2, "max_runtime_seconds": 300, "max_cost_usd": 5}))
        self.assertTrue(r["needs_cost_confirmation"])
        self.assertFalse(dg.may_run(r))                                       # 確認前は実行しない
        self.assertTrue(dg.may_run(r, cost_confirmed_by_president=True))      # 要件が費用を禁止していなければ、確認後に実行できる

    def test_t3_07_cost_when_forbidden_by_requirement_is_violation(self):
        r = dg.check_definition(REQ, variant(definition__limits={"max_retries": 2, "max_runtime_seconds": 300, "max_cost_usd": 5}))
        self.assertFalse(r["ok"])
        self.assertFalse(dg.may_run(r, cost_confirmed_by_president=True))     # 要件が禁止していれば確認しても不可

    def test_t3_08_unset_limits_rejected(self):
        for k in ("max_retries", "max_runtime_seconds"):
            lim = {"max_retries": 2, "max_runtime_seconds": 300, "max_cost_usd": 0}
            lim[k] = None
            r = dg.check_definition(REQ, variant(definition__limits=lim))
            self.assertFalse(r["ok"], k)


class Sandbox(unittest.TestCase):
    def test_t3_05_only_sandbox_output_changes(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / "設定").mkdir(); (root / "設定" / "a.yaml").write_text("x", encoding="utf-8")
            (root / "out").mkdir()
            before = dg.snapshot(root)
            (root / "out" / "result.csv").write_text("r", encoding="utf-8")
            ch = dg.diff(before, dg.snapshot(root))
            self.assertEqual(dg.unexpected_changes(ch, ("out",)), [])
            (root / "設定" / "a.yaml").write_text("y", encoding="utf-8")          # 本番側を変えた
            (root / "設定" / "new.yaml").write_text("z", encoding="utf-8")
            ch = dg.diff(before, dg.snapshot(root))
            self.assertEqual(dg.unexpected_changes(ch, ("out",)), ["設定/a.yaml", "設定/new.yaml"])

    def test_t3_05_real_check_script_leaves_repo_unchanged(self):
        import subprocess
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "r.csv"
            before = dg.snapshot(ROOT, exclude=(".git", "データ/実行状態", "データ/private", "src/__pycache__"))
            before = {k: v for k, v in before.items() if "__pycache__" not in k and not k.endswith(".pyc")}
            subprocess.run([sys.executable, str(CODE), str(ROOT / "データ" / "fixtures" / "南紀白浜_サイト構造スナップショット.csv"), str(out)],
                           check=True, capture_output=True)
            after = dg.snapshot(ROOT, exclude=(".git", "データ/実行状態", "データ/private", "src/__pycache__"))
            after = {k: v for k, v in after.items() if "__pycache__" not in k and not k.endswith(".pyc")}
            self.assertEqual(dg.unexpected_changes(dg.diff(before, after), ()), [])
            self.assertTrue(out.exists())


class Approval(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.q = aq.ApprovalQueue(self._t.name, {"ttl_hours": 24})

    def tearDown(self):
        self._t.cleanup()

    def request(self):
        return dg.build_approval_request(self.q, REQ, DEF, [DEF_PATH, CODE])

    def test_request_binds_definition_and_code_hash(self):
        a, payload = self.request()
        self.assertEqual(a["risk"], "low")
        self.assertEqual(set(payload["files"]), {DEF_PATH.name, CODE.name})
        self.assertEqual(payload["files"][DEF_PATH.name], "a63ade51a124ce2e8bb34dfc21626608cac676a782a2b526888113647eaa36de")
        self.assertEqual(payload["files"][CODE.name], "be0a1435e0fb1e2310386229f2a7dd1a6db21399a6125216b41414efbe8dce24")

    def test_t3_10_register_before_approval_refused_and_logged(self):
        a, payload = self.request()
        done = []
        with self.assertRaises(aq.ApprovalError):
            dg.register_with_approval(self.q, a["approval_id"], payload, lambda: done.append(1))
        self.assertEqual(done, [])
        self.assertIn("denied_use", [h["event"] for h in self.q.history()])

    def test_t3_11_register_after_president_approval_once(self):
        a, payload = self.request()
        self.q.approve(a["approval_id"], "社長", payload, "確認済み")
        done = []
        dg.register_with_approval(self.q, a["approval_id"], payload, lambda: done.append(1))
        self.assertEqual(done, [1])
        with self.assertRaises(aq.ApprovalError):                                  # 1 回だけ
            dg.register_with_approval(self.q, a["approval_id"], payload, lambda: done.append(2))
        self.assertEqual(done, [1])

    def test_t3_09_changed_content_after_approval_invalidates(self):
        a, payload = self.request()
        self.q.approve(a["approval_id"], "社長", payload)
        changed = copy.deepcopy(payload)
        changed["files"][CODE.name] = "0" * 64
        done = []
        with self.assertRaises(aq.ApprovalError):
            dg.register_with_approval(self.q, a["approval_id"], changed, lambda: done.append(1))
        self.assertEqual(done, [])

    def test_t3_13_reject_records_reason_and_blocks(self):
        a, payload = self.request()
        self.q.reject(a["approval_id"], "社長", "目的が不明確")
        done = []
        with self.assertRaises(aq.ApprovalError):
            dg.register_with_approval(self.q, a["approval_id"], payload, lambda: done.append(1))
        self.assertEqual(done, [])
        self.assertTrue(any(h["event"] == "rejected" and "目的が不明確" in h.get("note", "") for h in self.q.history()))

    def test_ai_cannot_approve(self):
        a, payload = self.request()
        with self.assertRaises(aq.ApprovalError):
            self.q.approve(a["approval_id"], "AI-07-01", payload)


class Documents(unittest.TestCase):
    def test_t3_14_three_documents_present(self):
        doc = (ROOT / "文書" / "手順書" / "STEP3_試験役割_申請書類.md").read_text(encoding="utf-8")
        for h in ("## 1. 定義書", "## 2. テスト計画", "## 3. 承認依頼書"):
            self.assertIn(h, doc)
        self.assertTrue(DEF_PATH.is_file())
        for k in ("role_id", "definition", "history"):
            self.assertIn(k, DEF)


if __name__ == "__main__":
    unittest.main()
