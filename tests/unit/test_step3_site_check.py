"""STEP 3 試験役割（観光サイト構成確認 AI）の模擬実行。期待: あり 10 / 不明 3。"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tests" / "step3-sandbox" / "site_check"))
import check  # noqa: E402

SNAP = ROOT / "データ" / "fixtures" / "南紀白浜_サイト構造スナップショット.csv"


class T(unittest.TestCase):
    def test_expected_result(self):
        with tempfile.TemporaryDirectory() as d:
            res = check.run(SNAP, Path(d) / "out.csv")
        by = {r["判定"] for r in res}
        self.assertEqual(sum(r["判定"] == "あり" for r in res), 10)
        self.assertEqual(sum(r["判定"] == "不明" for r in res), 3)
        self.assertEqual(by, {"あり", "不明"})            # 「なし」を推測で出さない
        self.assertTrue(all(r["根拠URL"] for r in res if r["判定"] == "あり"))

    def test_rejects_input_outside_fixtures(self):      # T3-06
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "x.csv"; bad.write_text("確認項目,URL\nA,http://x\n", encoding="utf-8")
            with self.assertRaises(PermissionError): check.run(bad, Path(d) / "o.csv")
            with self.assertRaises(PermissionError): check.run(ROOT / "設定" / "org.yaml", Path(d) / "o.csv")

    def test_missing_column(self):
        with tempfile.TemporaryDirectory() as d:
            p = ROOT / "データ" / "fixtures" / "ダミー自治体サイト一覧.csv"
            with self.assertRaises(ValueError): check.run(p, Path(d) / "o.csv")   # T3-01 相当


if __name__ == "__main__":
    unittest.main()
