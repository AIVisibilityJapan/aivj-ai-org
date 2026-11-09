"""zip の中の『生成ツールの本命』だけを、読み取り専用で新しいフォルダに取り出す（前回の一括抽出の続き）。

使い方: py scripts\\aiv_zip_extract_targets.py
対象: Batch38 の作業フォルダ、append9、選定の生成スクリプト、p0 binding の作業、各版の manifest 類。
元の zip は変更しない。パスに .. や絶対パスを含む項目は取り出さない。上限 2,500 件・200MB。
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
TARGETS = [
    ("batch38_build", re.compile(r"report_build_20261028_batch38/", re.I)),
    ("append9", re.compile(r"append9", re.I)),
    ("selector_build_scripts", re.compile(r"/03_generated/scripts/(build_|finalize_|aiv_diagnostic_resource_selector)", re.I)),
    ("p0_binding_work", re.compile(r"aiv_p0_binding_work_20261029/", re.I)),
    ("outputs_manifests", re.compile(r"CURRENT/outputs/[^/]*(selector|common_asset|apa_mapping|gate|source_contract)[^/]*/[^/]*(readme|manifest|build|provenance|summary|audit)[^/]*\.(md|json|txt|py)$", re.I)),
]
SKIP_PATH = re.compile(r"(node_modules|site-packages|\.venv|/venv/|\.codex|/plugins/)", re.I)
MAX_FILES = 2500
MAX_TOTAL = 200 * 1024 * 1024
MAX_EXTRACT = 2 * 1024 * 1024
OUT = R / "データ" / "private" / "06-STEP4作業" / "資源確認" / "出力" / f"zip対象抽出_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"


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
                    tag = next((n for n, rx in TARGETS if rx.search(zi.filename)), "")
                    hit = bool(tag) and not SKIP_PATH.search(zi.filename)
                    if hit:
                        listing.append({"zip": str(zp), "entry": zi.filename, "size": zi.file_size, "name_hit": tag})
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
                    extracted.append({"target": tag, "zip": str(zp), "entry": zi.filename, "size": zi.file_size, "sha256": sha(data), "extracted_to": str(dest)})
        except Exception as e:  # noqa: BLE001
            listing.append({"zip": str(zp), "entry": f"[ERROR] {e}", "size": 0, "name_hit": False})
        print("済:", zp.name)
    for name, rows, cols in (("01_zip_entry_listing.csv", listing, ["zip", "entry", "size", "name_hit"]),
                             ("02_extracted_files.csv", extracted, ["target", "zip", "entry", "size", "sha256", "extracted_to"])):
        with (OUT / name).open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    print(f"zip {len(zips)} / 対象に当たった項目 {len(listing)} / 取り出した写し {len(extracted)}\n出力: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
