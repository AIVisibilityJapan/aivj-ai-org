"""zip の中の生成ツール候補を、読み取り専用で一覧し、必要なものだけ『別の新しいフォルダ』に取り出す。

使い方（PowerShell、リポジトリ直下）:
    py scripts\\aiv_zip_probe.py

やること:
  1) 次の zip（読み取り専用で開く。元は変更しない・移動しない・削除しない）の中身の『名前一覧』を作る
       データ\\private\\05-測定データ\\AIV_PC_PRESERVATION_20261102\\ARCHIVES\\*.zip
       データ\\private\\05-測定データ\\AIV_RECOVERY_SOURCES\\**\\*.zip
       データ\\private\\05-測定データ\\AIV_NEW_PC_HANDOFF_20261105\\**\\*.zip
  2) 名前が検索語（build_・append・regress・binding・s1549・s1550・s1551・1_5_49〜1_5_51・1_1_25・1_1_31・batch38 など）に当たる
     コード・設定・文書のうち、2MB 以下のものを、新しいフォルダ 出力\\zip抽出_日時\\ に取り出す（SHA-256 を記録）
     ※ zip のパスが『..』や絶対パスの項目は取り出さない
外部通信・API 実行・正式データの変更はありません。取り出したものは調査用の写しです。
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import re
import sys
import zipfile
from pathlib import Path

R = Path(__file__).resolve().parents[1]
BASE = R / "データ" / "private" / "05-測定データ"
ZIP_ROOTS = [BASE / "AIV_PC_PRESERVATION_20261102" / "ARCHIVES", BASE / "AIV_RECOVERY_SOURCES", BASE / "AIV_NEW_PC_HANDOFF_20261105"]
CODE_EXT = {".py", ".ps1", ".bat", ".cmd", ".sh", ".json", ".md", ".txt", ".yaml", ".yml", ".sql", ".cfg", ".ini"}
NAME_RE = re.compile(r"(build_|append|regress|binding|bind_|s1549|s1550|s1551|1_5_49|1_5_5[01]|1_1_25|1_1_3[01]|batch38|preflight|finalize|prepare_|validate_)", re.I)
PROV_RE = re.compile(r"(readme|manifest|provenance|release_record|summary)", re.I)
PATH_RE = re.compile(r"(report_build|batch38|selector|common_asset|apa_mapping|resource_preflight|source_contract)", re.I)
SKIP_PATH = re.compile(r"(node_modules|site-packages|\.venv|/venv/|\.codex|/plugins/)", re.I)
MAX_FILES = 4000
MAX_TOTAL = 400 * 1024 * 1024
MAX_EXTRACT = 2 * 1024 * 1024
OUT = R / "データ" / "private" / "06-STEP4作業" / "資源確認" / "出力" / f"zip抽出_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    OUT.mkdir(parents=True, exist_ok=False)
    (OUT / "files").mkdir()
    zips = sorted({p for root in ZIP_ROOTS if root.exists() for p in root.rglob("*.zip")})
    listing, extracted = [], []
    total_bytes = 0
    for zp in zips:
        try:
            with zipfile.ZipFile(zp) as z:
                for zi in z.infolist():
                    if zi.is_dir():
                        continue
                    ext = Path(zi.filename).suffix.lower()
                    if ext not in CODE_EXT:
                        continue
                    hit = bool(NAME_RE.search(zi.filename) or (PROV_RE.search(zi.filename) and PATH_RE.search(zi.filename))) and not SKIP_PATH.search(zi.filename)
                    listing.append({"zip": str(zp), "entry": zi.filename, "size": zi.file_size, "name_hit": hit})
                    if not hit or zi.file_size > MAX_EXTRACT or len(extracted) >= MAX_FILES or total_bytes >= MAX_TOTAL:
                        continue
                    parts = Path(zi.filename).parts
                    if zi.filename.startswith(("/", "\\")) or ".." in parts or ":" in zi.filename:
                        continue
                    data = z.read(zi)
                    dest = OUT / "files" / zp.stem[:40] / Path(*parts)
                    if len(str(dest)) > 240:  # Windows のパス長対策
                        dest = OUT / "files" / zp.stem[:40] / ("LONG_" + sha(zi.filename.encode())[:12] + "_" + parts[-1])
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
                    total_bytes += len(data)
                    extracted.append({"zip": str(zp), "entry": zi.filename, "size": zi.file_size, "sha256": sha(data), "extracted_to": str(dest)})
        except Exception as e:  # noqa: BLE001
            listing.append({"zip": str(zp), "entry": f"[ERROR] {e}", "size": 0, "name_hit": False})
        print("済:", zp.name)
    for name, rows, cols in (("01_zip_entry_listing.csv", listing, ["zip", "entry", "size", "name_hit"]),
                             ("02_extracted_files.csv", extracted, ["zip", "entry", "size", "sha256", "extracted_to"])):
        with (OUT / name).open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    print(f"zip {len(zips)} / コード・設定・文書の項目 {len(listing)} / 取り出した写し {len(extracted)}\n出力: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
