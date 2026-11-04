"""差戻しログ（1 ファイル・新しい順）に、確認結果・変更の実施を 1 行加える。既存の行は書き換えない。
使い方（PowerShell）:
  py scripts\\rejection_log_add.py --kind 確認結果 --ref P-1.audit --content "社長: ひな形を直す" --where "ひな形の協会名" --revert "旧版を戻す" --by 社長
  py scripts\\rejection_log_add.py --kind 変更の実施 --ref P-1.audit --content "協会名を修正" --where "FMT の 2 枚目" --revert "FMT_v2.22 の旧版を戻す" --by Claude
既定のログ: データ\\実行状態\\差戻しログ.md（--log で変更可）"""
import argparse, sys
from pathlib import Path
R = Path(__file__).parents[1]
sys.path.insert(0, str(R / "src" / "shared"))
import rejection_log as rl

a = argparse.ArgumentParser()
a.add_argument("--kind", required=True, choices=rl.KINDS)
a.add_argument("--ref", required=True)
a.add_argument("--content", required=True)
a.add_argument("--where", default="")
a.add_argument("--revert", default="")
a.add_argument("--by", default="")
a.add_argument("--log", default=str(R / "データ" / "実行状態" / "差戻しログ.md"))
x = a.parse_args()
if x.kind == "変更の実施" and not x.revert:
    sys.exit("『変更の実施』には --revert（見直し方・元に戻す方法）が必要です")
rl.append(x.log, x.kind, x.ref, x.content, x.where, x.revert, x.by or "（未記入）")
print("加筆しました:", x.log)
