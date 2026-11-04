"""役割台帳の整合検証（STEP 2 / 2-2）。使い方: python scripts/validate_roles.py [--export roles.json]
食い違いがあれば内容を列挙して終了コード 1 を返す。API・DB・外部通信は使わない。"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src" / "shared"))
import role_registry as rr  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", help="検証後に役割一覧を JSON で書き出す（将来の DB 取込用）")
    a = ap.parse_args()
    roles, errors, info = rr.validate(ROOT)
    for line in info: print("INFO", line)
    for e in errors: print("NG  ", e)
    print(f"結果: {'OK' if not errors else 'NG'}（役割 {len(roles)}、エラー {len(errors)}）")
    if a.export and not errors:
        rr.export_json(roles, a.export); print("書き出し:", a.export)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
