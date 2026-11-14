#!/usr/bin/env python3
"""候補抽出ツール v1(aiv_extract_candidates_one.py) と v2(aiv_extract_candidates_one_v2.py) の回帰テスト・差分監査。
両版を同じ自治体で実行し（どちらも完全読み取り専用・新規フォルダにだけ出力）、次を確認する:
  R1 00〜06 の各CSVは、common_match_detail 列を除いて完全一致（v2 は既存結果を再現する）
  R2 common_match_detail は『自分との関係=…』の部分だけが異なってよい。v1 に関係があった行は v2 でも同じ（v1 ⊆ v2）
  R3 07_common_asset_relations.csv: v1 の行はすべて v2 に含まれる。v2 だけの行は、municipality_id の MUNI_ 接頭辞違い（旧形式ID）だけで説明できる
  R4 08_summary.json: common_asset_relations 以外は一致。source_files_changed は両版とも空
どれか1つでも崩れたら FAIL。結果は --report に新規JSONで出力（既存ファイルは上書きしない）。
使い方（リポジトリ直下）: py scripts\\aiv_extract_v2_regress.py --report <新規.json> 八幡市:京都府 和泉市:大阪府 ...
"""
import argparse, csv, json, re, subprocess, sys, time
from pathlib import Path

R = Path(__file__).resolve().parents[1]
OUTROOT = R / "データ/private/06-STEP4作業/資源確認/出力"
FILES = ["00_gate_selector.csv", "01_appearance_candidates_raw.csv", "02_appearance_candidates_summary.csv", "03_appearance_top5_and_missing.csv",
         "04_apa_self_win_reasons.csv", "05_apa_self_resource_mentions.csv", "06_apa_self_resource_summary.csv"]

def rcsv(p):
    with open(p, encoding="utf-8-sig", newline="") as f: return list(csv.DictReader(f))
def bare(m): return m[5:] if (m or "").startswith("MUNI_") else (m or "")
def rel_part(s): return re.sub(r".*自分との関係=", "", s)

def run(script, name, pref):
    time.sleep(1.5)   # 出力フォルダ名は秒単位の日時のため、v1/v2 が同じ秒に重ならないようにする
    before = {p.name for p in OUTROOT.glob(f"候補抽出_{name}_*")}
    r = subprocess.run([sys.executable, str(R / "scripts" / script), name, pref], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=R)
    if r.returncode != 0: raise SystemExit(f"{script} が失敗: {r.stderr[-800:]}")
    new = sorted({p.name for p in OUTROOT.glob(f"候補抽出_{name}_*")} - before)
    if len(new) != 1: raise SystemExit(f"出力フォルダを特定できない: {new}")
    return OUTROOT / new[0]

def compare(d1, d2):
    res = {"R1": True, "R2": True, "R3": True, "R4": True, "notes": []}
    for fn in FILES:
        a, b = rcsv(d1 / fn), rcsv(d2 / fn)
        if len(a) != len(b): res["R1"] = False; res["notes"].append(f"{fn}: 行数 {len(a)} vs {len(b)}"); continue
        for i, (x, y) in enumerate(zip(a, b)):
            xs = {k: v for k, v in x.items() if k != "common_match_detail"}; ys = {k: v for k, v in y.items() if k != "common_match_detail"}
            if xs != ys: res["R1"] = False; res["notes"].append(f"{fn} 行{i + 2}: detail以外が相違"); break
            if "common_match_detail" in x:
                dx, dy = x["common_match_detail"], y["common_match_detail"]
                px, py = dx.split(" ; "), dy.split(" ; ")
                if len(px) != len(py) or any(u.split("|自分との関係=")[0] != v.split("|自分との関係=")[0] for u, v in zip(px, py)):
                    res["R2"] = False; res["notes"].append(f"{fn} 行{i + 2}: detailの資産部分が相違")
                else:
                    for u, v in zip(px, py):
                        ru, rv = rel_part(u), rel_part(v)
                        if ru != "なし" and not set(ru.split(",")) <= set(rv.split(",")): res["R2"] = False; res["notes"].append(f"{fn} 行{i + 2}: v1の関係がv2で失われた")
    a, b = rcsv(d1 / "07_common_asset_relations.csv"), rcsv(d2 / "07_common_asset_relations.csv")
    key = lambda r: tuple(r.get(k, "") for k in ("asset_id", "relation_type", "relation_status"))
    kb = {key(r) for r in b}
    if not {key(r) for r in a} <= kb: res["R3"] = False; res["notes"].append("07: v1の行がv2に無い")
    res["v1_rel_rows"], res["v2_rel_rows"] = len(a), len(b)
    s1, s2 = json.loads((d1 / "08_summary.json").read_text(encoding="utf-8")), json.loads((d2 / "08_summary.json").read_text(encoding="utf-8"))
    for k in s1:
        if k != "common_asset_relations" and s1[k] != s2.get(k): res["R4"] = False; res["notes"].append(f"08: {k} が相違")
    if s1.get("source_files_changed") or s2.get("source_files_changed"): res["R4"] = False; res["notes"].append("08: 入力が変更された")
    res["PASS"] = all(res[k] for k in ("R1", "R2", "R3", "R4")); return res

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--report", required=True, type=Path); ap.add_argument("targets", nargs="+")
    a = ap.parse_args()
    if a.report.exists(): raise SystemExit("report が既に存在する（上書きしない）")
    out = {}
    for t in a.targets:
        name, pref = t.split(":")
        d1 = run("aiv_extract_candidates_one.py", name, pref); d2 = run("aiv_extract_candidates_one_v2.py", name, pref)
        out[t] = {"v1_dir": d1.name, "v2_dir": d2.name, **compare(d1, d2)}; print(t, "PASS" if out[t]["PASS"] else "FAIL", out[t]["notes"][:3])
    allp = all(v["PASS"] for v in out.values())
    a.report.write_text(json.dumps({"ALL_PASS": allp, "results": out}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("ALL_PASS" if allp else "FAIL"); sys.exit(0 if allp else 1)

if __name__ == "__main__":
    main()
