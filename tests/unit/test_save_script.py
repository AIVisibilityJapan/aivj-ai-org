import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("save", Path(__file__).resolve().parents[2] / "scripts" / "save.py")
save = importlib.util.module_from_spec(spec); spec.loader.exec_module(save)


def test_secret_patterns_block():
    for n in [".env", ".env.local", "a/b/key.pem", "データ/private/x.pptx", "設定/担当者/registry.yaml", "id_rsa"]:
        assert save.SECRET.search(n), n


def test_normal_files_pass():
    for n in ["src/aiv/pins.yaml", ".env.example".replace(".env.example", "文書/判断ログ/README.md"), "scripts/save.py"]:
        assert not save.SECRET.search(n), n


def _fresh_repo(tmp_path):
    """コミットが 1 つもない新規リポジトリ（main）に save.py を置く。"""
    import shutil
    import subprocess
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(Path(save.__file__), repo / "scripts" / "save.py")
    for c in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
        subprocess.run(["git", *c], cwd=repo, check=True)
    return repo


def _save(repo, *args):
    import subprocess
    return subprocess.run([__import__("sys").executable, str(repo / "scripts" / "save.py"), *args],
                          cwd=repo, text=True, encoding="utf-8", errors="replace", capture_output=True,
                          env=dict(__import__("os").environ, PYTHONIOENCODING="utf-8"))


def _count(repo):
    import subprocess
    r = subprocess.run(["git", "rev-list", "--count", "--all"], cwd=repo, text=True, capture_output=True)
    return int(r.stdout.strip() or 0)


def test_fresh_repo_without_commit(tmp_path):
    repo = _fresh_repo(tmp_path)
    (repo / "a.txt").write_text("x", encoding="utf-8")
    r = _save(repo, "m", "--skip-tests", "--dry-run")
    assert r.returncode == 0 and _count(repo) == 0, r.stdout + r.stderr          # 確認のみ: 保存しない
    (repo / ".env").write_text("K=1", encoding="utf-8")
    r = _save(repo, "m", "--skip-tests", "--yes", "--no-push")
    assert r.returncode == 1 and "秘密" in r.stdout and _count(repo) == 0        # 秘密で停止
    (repo / ".env").unlink()
    r = _save(repo, "初回", "--skip-tests", "--yes", "--no-push")
    assert r.returncode == 0 and _count(repo) == 1, r.stdout + r.stderr          # 最初の commit
    r = _save(repo, "もう一度", "--skip-tests", "--yes", "--no-push")
    assert r.returncode == 0 and "変更はありません" in r.stdout and _count(repo) == 1
