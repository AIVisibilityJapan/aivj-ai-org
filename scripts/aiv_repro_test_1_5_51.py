#!/usr/bin/env python3
"""1.5.51 再現試験（一時出力のみ）。
build_append9.py を一時フォルダで実行し、現行 1.5.51 / Common Asset 1.1.31 と照合する。
リポジトリ内の正式データ・pointer・Gate には触れない。出力は新規フォルダのみ。
実行: リポジトリ直下で  py scripts\\aiv_repro_test_1_5_51.py
"""
from __future__ import annotations
import csv, hashlib, json, subprocess, sys, zipfile
from datetime import datetime
from pathlib import Path

REPO = Path.cwd().resolve()
MEAS = REPO / "データ" / "private" / "05-測定データ"
WORK_BASE = REPO / "データ" / "private" / "06-STEP4作業" / "資源確認"
INPUT = WORK_BASE / "入力"
TOOL = WORK_BASE / "ツール写し" / "119__build_append9.py"
TS = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT = WORK_BASE / "出力" / f"再現試験_{TS}"
TMP = Path("C:/dev") / f"aivj_repro_{TS}"          # パスを短くする（Windows 260字対策）
SRC, STAGE, WS = TMP / "src", TMP / "stage", TMP / "ws"
APA_SHA_PREF = "7f9a93e85122d453056e3b1a77bcf6e32de55bcaa828c7f524a78768c59b5ab9"
ZIP_ORDER = [("RUNTIME_S1550_LOCAL_R1.zip", "AIV_RUNTIME_S1550/"), ("CURRENT_LOCAL_R1.zip", "CURRENT/")]
NEED = [
    ("outputs/AIV_common_asset_v1_1_30_apa_mapping_v1_1_29_batch38_20261028/", ".csv"),
    ("outputs/AIV_diagnostic_selector_v1_5_50_batch38_20261028/01_SELECTOR/", ".csv"),
    ("03_実行基盤・コード/03_診断レポート/現行レポート基盤/03_generated/config/diagnostic_light_report_selector_binding.json", None),
    ("03_実行基盤・コード/03_診断レポート/現行レポート基盤/03_generated/config/appearance_datasource.json", None),
    ("03_実行基盤・コード/03_診断レポート/現行レポート基盤/03_generated/scripts/aiv_selector_v1_5_50_pinned.py", None),
]

def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()

def want(rel: str) -> bool:
    for pre, suf in NEED:
        if suf is None and rel == pre: return True
        if suf and rel.startswith(pre) and rel.endswith(suf): return True
    return False

def extract():
    got = set(); log = []
    for zname, pref in ZIP_ORDER:
        zp = next(MEAS.rglob(zname), None)
        if not zp: log.append((zname, "NOT_FOUND")); continue
        with zipfile.ZipFile(zp) as z:
            for info in z.infolist():
                if info.is_dir() or not info.filename.startswith(pref): continue
                rel = info.filename[len(pref):]
                if ".." in rel.split("/") or rel.startswith("/") or ":" in rel: continue
                if not want(rel) or rel in got: continue
                dst = SRC / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(z.read(info))
                got.add(rel); log.append((zname, rel))
    return log

def readcsv(p: Path):
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f); return list(r.fieldnames or []), list(r)

def main():
    if not TOOL.exists(): raise SystemExit(f"builder copy missing: {TOOL}")
    OUT.mkdir(parents=True); TMP.mkdir(parents=True); WS.mkdir()
    summary = {"started": TS, "formal_changes": 0, "pointer_changes": 0, "api_calls": 0}
    # 1) 入力の取り出し
    log = extract()
    (OUT / "01_extract_log.txt").write_text("\n".join(f"{a}\t{b}" for a, b in log), encoding="utf-8")
    summary["extracted_files"] = len([1 for a, b in log if b != "NOT_FOUND"])
    # 2) sqlite の選択（SHA 照合）
    cands = sorted(MEAS.rglob("apa_v1_report_mart.sqlite"))
    rows = [{"path": str(c), "bytes": c.stat().st_size, "sha256": sha(c), "match_expected": sha(c) == APA_SHA_PREF} for c in cands]
    with (OUT / "02_apa_sqlite_candidates.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    pick = next((r for r in rows if r["match_expected"]), None)
    summary["apa_sqlite_sha_match"] = bool(pick)
    if not pick: pick = rows[0]
    dst = SRC / "01_正式成果物/02_APA/Report Mart/正式データ/01_MART/apa_v1_report_mart.sqlite"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(Path(pick["path"]).read_bytes())
    summary["apa_sqlite_used"] = pick["path"]
    # 3) builder 実行（一時フォルダのみ）
    r = subprocess.run([sys.executable, str(TOOL), str(SRC), str(STAGE), str(WS)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    (OUT / "03_builder_stdout.txt").write_text(r.stdout + "\n--- STDERR ---\n" + r.stderr, encoding="utf-8")
    summary["builder_returncode"] = r.returncode
    if r.returncode != 0:
        summary["verdict"] = "REPRO_BUILDER_FAILED"
        (OUT / "00_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2)); return
    # 4) ファイル SHA 照合
    pairs = {
        "common_tourism_asset_master_v1_1_31.csv": "01_ASSET_MASTER",
        "common_tourism_asset_alias_v1_1_24.csv": "02_ALIAS",
        "common_asset_municipality_relation_v1_1_31.csv": "03_RELATIONS",
        "appearance_common_asset_mapping_v1_1_12.csv": "05_SOURCE_MAPPING",
        "apa_common_asset_mapping_v1_1_30.csv": "05_SOURCE_MAPPING",
        "apa_common_asset_source_lineage_v1_1_30.csv": "05_SOURCE_MAPPING",
    }
    pkg = STAGE / "outputs/AIV_common_asset_v1_1_31_apa_mapping_v1_1_30_reaudit9_20261030"
    cmp = []
    for name, sub in pairs.items():
        a, b = INPUT / name, pkg / sub / name
        cmp.append({"file": name, "current_sha": sha(a) if a.exists() else "", "rebuilt_sha": sha(b) if b.exists() else "", "same": a.exists() and b.exists() and sha(a) == sha(b)})
    slot_name = "diagnostic_selector_v1_5_51_formal_slots_common_v1_1_31_apa_mapping_v1_1_30.csv"
    cur_slot, new_slot = INPUT / slot_name, STAGE / "outputs/AIV_diagnostic_selector_v1_5_51_reaudit9_20261030/01_SELECTOR" / slot_name
    cmp.append({"file": slot_name, "current_sha": sha(cur_slot), "rebuilt_sha": sha(new_slot), "same": sha(cur_slot) == sha(new_slot)})
    with (OUT / "04_file_sha_compare.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(cmp[0])); w.writeheader(); w.writerows(cmp)
    # 5) スロット照合
    cf, cr = readcsv(cur_slot); nf, nr = readcsv(new_slot)
    ci = {(x["municipality_id"], x["display_slot"]): x for x in cr}
    ni = {(x["municipality_id"], x["display_slot"]): x for x in nr}
    munis_c = {k[0] for k in ci}; munis_n = {k[0] for k in ni}
    exact = 0; diffs = []
    cnt = {"order": 0, "source_tier": 0, "common_asset_id": 0, "canonical_name": 0, "relation_type": 0, "unexpected": 0, "missing": 0}
    for k, c in ci.items():
        n = ni.get(k)
        if n is None: cnt["missing"] += 1; diffs.append({"key": k, "col": "(missing)", "cur": "", "new": ""}); continue
        bad = [col for col in cf if c.get(col, "") != n.get(col, "")]
        if not bad: exact += 1
        else:
            cnt["unexpected"] += 1
            for col in bad:
                if col in cnt: cnt[col] += 1
                diffs.append({"key": "|".join(k), "col": col, "cur": c.get(col, ""), "new": n.get(col, "")})
    with (OUT / "05_slot_diff.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["key", "col", "cur", "new"]); w.writeheader(); w.writerows(diffs)
    summary.update({
        "municipalities": f"{len(munis_c & munis_n)}/{len(munis_c)}",
        "slots_exact": f"{exact}/{len(ci)}", "slot_columns_equal_header": cf == nf,
        "mismatch_counts": cnt, "all_files_sha_same": all(x["same"] for x in cmp),
    })
    ok = exact == len(ci) == 5223 and len(munis_c & munis_n) == 1741 and summary["all_files_sha_same"] and cf == nf
    summary["verdict"] = "REPRO_PASS" if ok else "REPRO_MISMATCH"
    summary["temp_dir_kept"] = str(TMP)
    (OUT / "00_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2)); print("出力:", OUT)

if __name__ == "__main__":
    main()
