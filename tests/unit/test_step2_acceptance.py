"""2-9 総合試験の対応表。T2-01〜T2-14 のそれぞれに、確認する自動試験（または手動確認）が実在することを確かめる。
試験の実行そのもの（合否）は tests/unit 全体の実行で見る。ここは『試験項目に抜けがない』ことの検査。"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
U = ROOT / "tests" / "unit"

# 項目 → [(試験ファイル, 試験名)]。手動確認は ("manual", 説明)
MAP = {
    "T2-01": [("test_coo.py", "test_t2_01_a_to_b_completes_without_manual_steps")],
    "T2-02": [("test_coo.py", "test_t2_02_no_duplicate_registration_or_run"), ("test_task_engine.py", "test_no_double_execution_threads")],
    "T2-03": [("test_coo.py", "test_t2_03_blocked_until_approved"), ("test_coo.py", "test_t2_03_expired_or_changed_not_run")],
    "T2-04": [("test_coo.py", "test_t2_04_retry_stops_and_queues_human")],
    "T2-05": [("test_coo.py", "test_t2_05_cost_stops_and_logs")],
    "T2-06": [("test_coo.py", "test_t2_06_limits_unset_does_not_start"), ("test_task_engine.py", "test_fail_closed_when_limits_unset")],
    "T2-07": [("test_coo.py", "test_t2_07_stop_and_only_human_resumes")],
    "T2-08": [("test_coo.py", "test_t2_08_circuit_breaker_stops_role")],
    "T2-09": [("test_coo.py", "test_t2_09_failure_log_and_rollback_proposal")],
    "T2-10": [("test_cost_report.py", "test_by_day_role_project"), ("test_cost_report.py", "test_total_matches_engine")],
    "T2-11": [("test_coo.py", "test_t2_11_new_dummy_role_needs_no_core_change")],
    "T2-12": [("test_coo.py", "test_t2_12_coo_cannot_write_approvals_or_resume")],
    # 共通 DB（RLS）は使わない方針（D-025）のため、同じ目的（権限のない主体が読めない）を OS の権限で満たす
    "T2-13": [("manual", "データ/実行状態 と データ/private を社長のアカウントだけに絞った（icacls、2026-11-04 確認済み）。手順: 文書/手順書/権限の絞り方.md")],
    "T2-14": [("test_backup_restore.py", "test_backup_verify_restore_roundtrip"), ("test_backup_restore.py", "test_tampered_zip_refused")],
}


class Acceptance(unittest.TestCase):
    def test_all_items_are_mapped(self):
        self.assertEqual(sorted(MAP), [f"T2-{i:02d}" for i in range(1, 15)])

    def test_every_mapped_test_exists(self):
        for tid, refs in MAP.items():
            self.assertTrue(refs, tid)
            for f, name in refs:
                if f == "manual":
                    self.assertTrue(name.strip(), tid)
                    continue
                src = (U / f).read_text(encoding="utf-8")
                self.assertTrue(re.search(rf"def {name}\(", src), f"{tid}: {f}::{name} が見つかりません")

    def test_runtime_state_not_in_git(self):
        gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("データ/実行状態/", gi)
        self.assertIn("データ/private/", gi)


if __name__ == "__main__":
    unittest.main()
