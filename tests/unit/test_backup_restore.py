"""T2-14 バックアップから復元できる。"""
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src" / "orchestrator"))
import backup_state as bs  # noqa: E402
import task_engine as te  # noqa: E402

LIM = {"max_retries": 2, "max_runtime_seconds": 300, "consecutive_failures_to_stop_role": 3, "max_cost_usd": 0}


class Backup(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.repo = self.tmp / "repo"
        self.state = self.repo / "データ" / "実行状態"
        (self.repo / "設定" / "担当者").mkdir(parents=True)
        (self.repo / "設定" / "担当者" / "registry.yaml").write_text("people: []\n", encoding="utf-8")
        (self.repo / "データ" / "private" / "01-顧客別").mkdir(parents=True)
        (self.repo / "データ" / "private" / "01-顧客別" / "a.txt").write_text("顧客情報", encoding="utf-8")
        eng = te.TaskEngine(self.state, LIM)
        eng.submit("P-1.a", "AI-X", payload={"v": 1})
        eng.stop("D07", reason="試験")
        self.dest = self.tmp / "backup"

    def tearDown(self):
        self._t.cleanup()

    def test_backup_verify_restore_roundtrip(self):
        z = bs.backup(self.dest, root=self.repo)
        bs.verify(z)
        out = self.tmp / "restored"
        n = bs.restore(z, out)
        self.assertGreaterEqual(n, 4)
        for p in self.state.rglob("*.json*"):
            q = out / p.relative_to(self.repo)
            self.assertEqual(p.read_bytes(), q.read_bytes(), p.name)
        eng = te.TaskEngine(out / "データ" / "実行状態", LIM)       # 復元した状態が実際に使える
        self.assertEqual(len(eng.all_tasks()), 1)
        self.assertEqual(eng.stopped(), {"D07"})
        self.assertEqual(eng.stop_log()[0]["reason"], "試験")

    def test_private_excluded_unless_asked(self):
        names = zipfile.ZipFile(bs.backup(self.dest, root=self.repo)).namelist()
        self.assertFalse(any("private" in n for n in names))
        z2 = bs.backup(self.dest, root=self.repo, with_private=True)
        self.assertTrue(any("private" in n for n in zipfile.ZipFile(z2).namelist()))

    def test_dest_required_and_not_inside_repo(self):
        with self.assertRaises(bs.BackupError):
            bs.backup("", root=self.repo)
        with self.assertRaises(bs.BackupError):
            bs.backup(self.repo / "backup", root=self.repo)

    def test_tampered_zip_refused(self):
        z = bs.backup(self.dest, root=self.repo)
        bad = self.tmp / "bad.zip"
        with zipfile.ZipFile(z) as src, zipfile.ZipFile(bad, "w") as dst:
            for n in src.namelist():
                data = src.read(n)
                if n.endswith("停止.json"):
                    data = b"[]"
                dst.writestr(n, data)
        with self.assertRaises(bs.BackupError):
            bs.verify(bad)
        with self.assertRaises(bs.BackupError):
            bs.restore(bad, self.tmp / "o")
        self.assertFalse((self.tmp / "o").exists())

    def test_missing_or_extra_file_refused(self):
        z = bs.backup(self.dest, root=self.repo)
        extra = self.tmp / "extra.zip"
        with zipfile.ZipFile(z) as src, zipfile.ZipFile(extra, "w") as dst:
            for n in src.namelist():
                dst.writestr(n, src.read(n))
            dst.writestr("データ/実行状態/追加.json", "{}")
        with self.assertRaises(bs.BackupError):
            bs.verify(extra)

    def test_zip_slip_refused(self):
        evil = self.tmp / "evil.zip"
        with zipfile.ZipFile(evil, "w") as z:
            import hashlib
            data = b"x"
            z.writestr("../evil.txt", data)
            z.writestr(bs.MANIFEST, json.dumps({"created": "x", "files": {"../evil.txt": {"sha256": hashlib.sha256(data).hexdigest(), "size": 1}}}))
        with self.assertRaises(bs.BackupError):
            bs.restore(evil, self.tmp / "dst")
        self.assertFalse((self.tmp / "evil.txt").exists())

    def test_restore_does_not_overwrite(self):
        z = bs.backup(self.dest, root=self.repo)
        out = self.tmp / "nonempty"
        out.mkdir()
        (out / "keep.txt").write_text("既存", encoding="utf-8")
        with self.assertRaises(bs.BackupError):
            bs.restore(z, out)
        self.assertEqual((out / "keep.txt").read_text(encoding="utf-8"), "既存")

    def test_not_a_zip(self):
        p = self.tmp / "x.zip"
        p.write_text("zipではない", encoding="utf-8")
        with self.assertRaises(bs.BackupError):
            bs.verify(p)

    def test_cli(self):
        self.assertEqual(bs.main(["backup"]), 1)
        blocker = self.tmp / "file.txt"
        blocker.write_text("x", encoding="utf-8")
        self.assertEqual(bs.main(["backup", "--dest", str(blocker / "sub")]), 1)   # 作れない保存先でも説明つきで終わる
        self.assertEqual(bs.main(["verify", "--file", str(self.tmp / "none.zip")]), 1)


if __name__ == "__main__":
    unittest.main()
