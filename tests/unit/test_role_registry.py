"""2-2 役割台帳の検証の試験。正常系と、わざと壊した複製での異常系（検出できること）。
実行: python -m unittest discover -s tests/unit -v"""
import csv
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src" / "shared"))
import role_registry as rr  # noqa: E402


class Sandbox:
    """リポジトリの必要部分だけを一時フォルダへ複製して、壊して検証する。"""
    def __enter__(self):
        self.tmp = Path(tempfile.mkdtemp())
        for d in (str(Path(rr.CSV_PATH).parent), rr.CONFIG_DIR, rr.SERVICES_DIR, rr.AGENTS_DIR):
            shutil.copytree(ROOT / d, self.tmp / d, ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))
        return self.tmp
    def __exit__(self, *a): shutil.rmtree(self.tmp, ignore_errors=True)


def edit_csv(root, fn):
    p = root / rr.CSV_PATH
    rows = list(csv.DictReader(io.StringIO(p.read_text(encoding="utf-8-sig"))))
    fn(rows)
    buf = io.StringIO(); w = csv.DictWriter(buf, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    p.write_text("﻿" + buf.getvalue(), encoding="utf-8", newline="")


def has(errors, token): return any(token in e for e in errors)


class TestRealRepo(unittest.TestCase):
    def test_repository_is_consistent(self):
        roles, errors, _ = rr.validate(ROOT)
        self.assertEqual(errors, [])
        self.assertEqual(len(roles), 59)

    def test_pilot_set(self):
        roles, _, _ = rr.validate(ROOT)
        self.assertEqual({r.role_id for r in roles if r.pilot}, {"AI-000", "AI-07-01", "AI-03-01", "AI-04-01", "AI-03-05", "AI-06-06"})


class TestDetectsProblems(unittest.TestCase):
    def test_duplicate_id(self):
        with Sandbox() as t:
            edit_csv(t, lambda rows: rows[1].__setitem__("role_id", rows[0]["role_id"]))
            self.assertTrue(has(rr.validate(t)[1], "重複"))

    def test_missing_role_yaml(self):
        with Sandbox() as t:
            (t / "src/AI社員/00-全社COO/AI-000_COO/role.yaml").unlink()
            self.assertTrue(has(rr.validate(t)[1], "ファイルがない"))

    def test_unknown_escalation(self):
        with Sandbox() as t:
            edit_csv(t, lambda rows: rows[3].__setitem__("escalate_to", "AI-999"))
            self.assertTrue(has(rr.validate(t)[1], "escalate_to が存在しない"))

    def test_yaml_differs_from_ledger(self):
        with Sandbox() as t:
            edit_csv(t, lambda rows: rows[0].__setitem__("role_name", "別名"))
            self.assertTrue(has(rr.validate(t)[1], "role_name が台帳と違う"))

    def test_head_before_step6(self):
        with Sandbox() as t:
            def f(rows):
                for r in rows:
                    if r["role_id"] == "AI-D02": r["build_step"] = "STEP5"
            edit_csv(t, f)
            self.assertTrue(has(rr.validate(t)[1], "部長 AI は STEP6"))

    def test_count_mismatch(self):
        with Sandbox() as t:
            edit_csv(t, lambda rows: rows.pop())
            self.assertTrue(has(rr.validate(t)[1], "件数が想定と違う"))

    def test_service_owner_not_head(self):
        with Sandbox() as t:
            p = t / "設定/services.yaml"
            p.write_text(p.read_text(encoding="utf-8").replace("owner_role: AI-D03", "owner_role: AI-03-01", 1), encoding="utf-8")
            self.assertTrue(has(rr.validate(t)[1], "部長 AI として存在しない"))

    def test_stray_role_yaml(self):
        with Sandbox() as t:
            d = t / "src/AI社員/01-営業部/ai-99_stray"; d.mkdir()
            (d / "role.yaml").write_text("role_id: AI-99\n", encoding="utf-8")
            self.assertTrue(has(rr.validate(t)[1], "台帳にない role.yaml"))


class TestAssignability(unittest.TestCase):
    def setUp(self):
        self.roles = {r.role_id: r for r in rr.validate(ROOT)[0]}

    def test_not_implemented_is_refused(self):
        ok, why = rr.assignability(self.roles["AI-01-01"])
        self.assertFalse(ok); self.assertIn("未実装", why)

    def test_implemented_is_assignable_unless_stopped(self):
        r = self.roles["AI-000"]
        impl = rr.Role(**{**r.__dict__, "impl_status": "implemented"})
        self.assertTrue(rr.assignability(impl)[0])
        for scope in ("all", "AI-000"):
            self.assertEqual(rr.assignability(impl, {scope}), (False, "停止中"))


if __name__ == "__main__":
    unittest.main()
