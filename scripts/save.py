"""保存の一括実行: 試験 → 役割定義の検証 → 変更の一覧 → 確認 → commit → push。

使い方（PowerShell、リポジトリ直下で）:
    py scripts\\save.py "メッセージ"            # 通常。commit の前に y/N で確認
    py scripts\\save.py "メッセージ" --dry-run   # 試験と変更一覧だけ。commit も push もしない
    py scripts\\save.py "メッセージ" --no-push   # commit まで（push しない）
    py scripts\\save.py "メッセージ" --yes       # 確認を省く（試験は省かない）
    py scripts\\save.py "メッセージ" --skip-tests  # 試験を省く（理由を書くこと、記録に残る）

止まる条件（fail closed）: 試験の失敗、役割定義の検証エラー、ステージされた
秘密らしいファイル（.env / private / 鍵）、ブランチが main 以外、commit の失敗。
止まったときは commit も push もしない。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRET = re.compile(r"(^|/)(\.env(\..*)?|.*\.(pem|key|pfx)|id_rsa.*)$|データ/private/|設定/担当者/registry\.yaml")
ATTRIBUTION = ""  # 共著表記が必要なら "Co-Authored-By: ..." をここに入れる


def run(cmd, check=True, capture=False):
    env = dict(os.environ, PYTHONUTF8="1")
    r = subprocess.run(cmd, cwd=ROOT, text=True, encoding="utf-8", errors="replace",
                       capture_output=capture, env=env)
    if check and r.returncode != 0:
        if capture:
            print(r.stdout or "", r.stderr or "")
        stop(f"失敗: {' '.join(cmd)}（終了コード {r.returncode}）")
    return r


def stop(msg):
    print(f"\n■ 止まりました: {msg}\n  commit も push もしていません。")
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("message")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--skip-tests", action="store_true")
    a = ap.parse_args()
    if not a.message.strip():
        stop("メッセージが空です")

    branch = run(["git", "symbolic-ref", "--short", "HEAD"], capture=True).stdout.strip()
    if branch != "main":
        stop(f"ブランチが main ではありません（{branch}）")

    if a.skip_tests:
        print("△ 試験を省きます（メッセージに記録します）")
    else:
        print("1/4 単体試験 …")
        run([sys.executable, "-m", "pytest", "tests/unit", "-q"])
        print("2/4 役割定義の検証 …")
        run([sys.executable, "scripts/validate_roles.py"])

    print("3/4 変更の一覧")
    run(["git", "add", "-A"])
    names = run(["git", "diff", "--cached", "--name-only", "-z"], capture=True).stdout.split("\0")
    names = [n for n in names if n]
    if not names:
        print("変更はありません。何もしません。")
        return
    bad = [n for n in names if SECRET.search(n.replace("\\", "/"))]
    if bad:
        run(["git", "reset", "-q"], check=False)
        stop("秘密らしいファイルが含まれています: " + ", ".join(bad))
    run(["git", "diff", "--cached", "--stat"])

    if a.dry_run:
        run(["git", "reset", "-q"], check=False)
        print("\n（--dry-run: ステージを戻しました。何も保存していません）")
        return
    if not a.yes:
        if input(f"\n{len(names)} 件を commit{'' if a.no_push else ' して push'} しますか？ [y/N] ").strip().lower() != "y":
            run(["git", "reset", "-q"], check=False)
            print("中止しました（ステージを戻しました）")
            return

    msg = a.message + ("\n\n（試験を省いて保存）" if a.skip_tests else "")
    if ATTRIBUTION:
        msg += "\n\n" + ATTRIBUTION
    print("4/4 commit" + ("" if a.no_push else " → push"))
    run(["git", "commit", "-q", "-m", msg])
    if not a.no_push:
        r = run(["git", "push"], check=False)
        if r.returncode != 0:
            print("\n■ push に失敗しました。commit は済んでいます。原因を解消して `git push` だけ再実行してください。")
            sys.exit(1)
    print("\n完了:", run(["git", "log", "--oneline", "-1"], capture=True).stdout.strip())


if __name__ == "__main__":
    main()
