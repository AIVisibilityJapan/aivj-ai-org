"""費用集計を CSV に書き出す（STEP 2 / 2-8）。読み取り専用。Excel で開ける（BOM 付き UTF-8）。
使い方（リポジトリのルートで）: py scripts/export_costs.py   → データ/実行状態/費用集計.csv
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src" / "shared"))
sys.path.insert(0, str(ROOT / "src" / "orchestrator"))
import cost_report as cr  # noqa: E402
import json  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state-dir", default=str(ROOT / "データ" / "実行状態"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    tasks = []
    for p in sorted((Path(a.state_dir) / "tasks").glob("*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                tasks.append(json.load(f))
        except (OSError, ValueError):
            print(f"警告: 読めないタスクがあります（集計から除外）: {p.name}")
    rate, _ = cr.load_rate(ROOT / "設定" / "budgets.yaml")
    out = cr.write_csv(cr.summarize(tasks), rate, a.out or Path(a.state_dir) / "費用集計.csv")
    print(f"作成しました: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
