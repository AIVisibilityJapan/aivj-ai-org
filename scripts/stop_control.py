"""緊急停止・再開・状態表示（STEP 2 / 2-4）。実行者と理由を停止ログに残す。
使い方（リポジトリのルートで）:
  python scripts/stop_control.py status
  python scripts/stop_control.py stop   all          --actor 社長 --reason "緊急"
  python scripts/stop_control.py resume all          --actor 社長 --reason "確認済み"
対象: all / 部コード（例 D07）/ 役割 ID（例 AI-000）
再開は --actor が必須。停止・再開の権限者は都度確認（Q-09）。
"""
import argparse
import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src" / "orchestrator"))
import task_engine as te  # noqa: E402

STATE = ROOT / "データ" / "実行状態"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["status", "stop", "resume"])
    ap.add_argument("target", nargs="?")
    ap.add_argument("--actor", default="")
    ap.add_argument("--reason", default="")
    ap.add_argument("--state-dir", default=str(STATE))
    a = ap.parse_args(argv)
    eng = te.TaskEngine(a.state_dir, {})
    if a.cmd == "status":
        print("停止中:", ", ".join(sorted(eng.stopped())) or "なし")
        for e in eng.stop_log()[-10:]:
            at = datetime.datetime.fromtimestamp(e["at"]).strftime("%Y-%m-%d %H:%M:%S")
            print(f"  {at} {e['event']:<9} {e['target']} / {e['actor']} / {e['reason']}")
        return 0
    if not a.target:
        print("対象（all / 部コード / 役割 ID）を指定してください"); return 2
    try:
        if a.cmd == "stop":
            eng.stop(a.target, actor=a.actor or "社長", reason=a.reason)
        else:
            eng.resume(a.target, actor=a.actor, reason=a.reason)
    except te.EngineError as e:
        print(f"エラー: {e}"); return 1
    print(f"{a.cmd}: {a.target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
