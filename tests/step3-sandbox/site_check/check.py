"""観光サイト構成確認 AI（試験用・STEP 3）。本番には登録しない。
入力: データ/fixtures/ 配下の CSV のみ（それ以外は拒否）。外部通信・費用・本番変更なし。
判定: 根拠 URL がある → あり ／ URL が無い → 不明（推測で「あり」「なし」にしない）。
実行: python check.py <入力CSV> <出力CSV>
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ALLOWED = (ROOT / "データ" / "fixtures").resolve()


def check_path(p: Path) -> Path:
    rp = p.resolve()
    if ALLOWED != rp and ALLOWED not in rp.parents:
        raise PermissionError(f"許可されていない入力です（データ/fixtures/ のみ）: {p}")
    return rp


def judge(rows):
    out = []
    for r in rows:
        url = (r.get("URL") or "").strip()
        out.append({"確認項目": r["確認項目"], "判定": "あり" if url else "不明", "根拠URL": url,
                    "備考": "" if url else "根拠となる URL がないため不明とする"})
    return out


def run(src: Path, dst: Path) -> list:
    src = check_path(src)
    with open(src, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for need in ("確認項目", "URL"):
        if rows and need not in rows[0]:
            raise ValueError(f"必須の列がありません: {need}")
    res = judge(rows)
    with open(dst, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["確認項目", "判定", "根拠URL", "備考"])
        w.writeheader(); w.writerows(res)
    return res


if __name__ == "__main__":
    run(Path(sys.argv[1]), Path(sys.argv[2]))
