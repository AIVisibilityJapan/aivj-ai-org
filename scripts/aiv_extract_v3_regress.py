#!/usr/bin/env python3
"""候補抽出ツール v2(正式版) と v3 の回帰テスト・差分監査。どちらも完全読み取り専用・新規フォルダにだけ出力する。
v2 は 1.5.51 時代の入力、v3 は --formal-root の現行データを読む。したがって自治体を 2 種類に分けて判定する。
  変更なし（現行データでも 1.5.51 時代から変わらない自治体）: aiv_extract_v2_regress.py の R1〜R4 をそのまま要求（完全一致）
  変更あり（追記・Gate解除を行った自治体。例: 八幡市・和泉市）: 次を要求し、増えた関係行を一覧に出して人が確認する
    C1 07_common_asset_relations.csv: v2 の行はすべて v3 に含まれる。ただし旧行が SUPERSEDED になったものは可。増えた行は、その SUPERSEDED 行か、新しい SELF_RESOURCE/ACTIVE 行だけ
    C2 v3 の 08_summary.json で source_files_changed が空（入力は変更されていない）
    C3 00〜06 は v2 に対し、行数が同じで、common_match_detail 以外の列の相違は一覧に出す（FAIL にはしない。測定データは同じため通常は相違なし）
どれか 1 つでも崩れたら FAIL。結果は --report に新規JSONで出力（既存ファイルは上書きしない）。
使い方（リポジトリ直下）:
  py scripts\\aiv_extract_v3_regress.py --formal-root "<...\\AI Visibility>" --report <新規.json> --unchanged 近江八幡市:滋賀県 野々市市:石川県 --changed 八幡市:京都府 和泉市:大阪府
"""
import argparse, json, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aiv_extract_v2_regress as v2r

R, OUTROOT = v2r.R, v2r.OUTROOT

def run3(name, pref, formal_root):
    time.sleep(1.5)
    before = {p.name for p in OUTROOT.glob(f"候補抽出_{name}_*")}
    r = subprocess.run([sys.executable, str(R / "scripts" / "aiv_extract_candidates_one_v3.py"), "--formal-root", str(formal_root), name, pref],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=R)
    if r.returncode != 0: raise SystemExit(f"v3 が失敗: {r.stdout[-400:]} {r.stderr[-800:]}")
    new = sorted({p.name for p in OUTROOT.glob(f"候補抽出_{name}_*")} - before)
    if len(new) != 1: raise SystemExit(f"出力フォルダを特定できない: {new}")
    return OUTROOT / new[0]

def run2(name, pref):
    return v2r.run("aiv_extract_candidates_one_v2.py", name, pref)

def compare_changed(d2, d3):
    res = {"C1": True, "C2": True, "notes": [], "added_relations": [], "superseded_changes": [], "other_diffs": []}
    for fn in v2r.FILES:
        a, b = v2r.rcsv(d2 / fn), v2r.rcsv(d3 / fn)
        if len(a) != len(b): res["other_diffs"].append(f"{fn}: 行数 {len(a)} → {len(b)}"); continue
        n = sum(1 for x, y in zip(a, b) if {k: v for k, v in x.items() if k != "common_match_detail"} != {k: v for k, v in y.items() if k != "common_match_detail"})
        if n: res["other_diffs"].append(f"{fn}: detail以外が相違の行 {n}")
    a, b = v2r.rcsv(d2 / "07_common_asset_relations.csv"), v2r.rcsv(d3 / "07_common_asset_relations.csv")
    key = lambda r: tuple(r.get(k, "") for k in ("asset_id", "relation_type", "relation_status"))
    ka, kb = {key(r) for r in a}, {key(r) for r in b}
    # 追記ツールは追記のみ。関係の訂正は「旧行を SUPERSEDED にし、新しい SELF_RESOURCE/ACTIVE 行を足す」形。これを正常な差分として扱う。
    lost = ka - kb
    superseded_ok = {k for k in lost if (k[0], k[1], "SUPERSEDED") in kb}
    unexplained = lost - superseded_ok
    if unexplained: res["C1"] = False; res["notes"].append(f"07: v2 の関係 {len(unexplained)} 行が v3 に無い（SUPERSEDED への変更でも説明できない）")
    res["v2_rel_rows"], res["v3_rel_rows"] = len(a), len(b)
    res["superseded_changes"] = [{"asset_id": k[0], "relation_type": k[1], "from": k[2], "to": "SUPERSEDED"} for k in sorted(superseded_ok)]
    names = {r["asset_id"]: r.get("canonical_name", "") for r in b}
    added = [r for r in b if key(r) not in ka]
    res["added_relations"] = [{"asset_id": r["asset_id"], "canonical_name": r.get("canonical_name", ""), "relation_type": r["relation_type"], "relation_status": r["relation_status"]} for r in added]
    # 増えた行は、(a) 旧行の SUPERSEDED 化、または (b) 新しい SELF_RESOURCE/ACTIVE 行のどちらかだけ
    odd = [r for r in added if not ((r["relation_status"] == "SUPERSEDED" and (r["asset_id"], r["relation_type"], "ACTIVE") in lost) or (r["relation_type"] == "SELF_RESOURCE" and r["relation_status"] == "ACTIVE"))]
    if odd: res["C1"] = False; res["notes"].append(f"07: 想定外の増えた行 {len(odd)}: " + ", ".join(f'{r.get("canonical_name","")}/{r["relation_type"]}/{r["relation_status"]}' for r in odd[:5]))
    s3 = json.loads((d3 / "08_summary.json").read_text(encoding="utf-8"))
    if s3.get("source_files_changed"): res["C2"] = False; res["notes"].append("08: 入力が変更された")
    res["v3_input_versions"] = s3.get("input_versions")
    res["PASS"] = res["C1"] and res["C2"]
    return res

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--formal-root", required=True, type=Path); ap.add_argument("--report", required=True, type=Path)
    ap.add_argument("--unchanged", nargs="*", default=[]); ap.add_argument("--changed", nargs="*", default=[])
    a = ap.parse_args()
    if a.report.exists(): raise SystemExit("report が既に存在する（上書きしない）")
    if not (a.unchanged or a.changed): raise SystemExit("--unchanged か --changed が必要")
    out = {}
    for kind, targets in (("unchanged", a.unchanged), ("changed", a.changed)):
        for t in targets:
            name, pref = t.split(":")
            d2 = run2(name, pref); d3 = run3(name, pref, a.formal_root)
            r = v2r.compare(d2, d3) if kind == "unchanged" else compare_changed(d2, d3)
            out[t] = {"kind": kind, "v2_dir": d2.name, "v3_dir": d3.name, **r}
            print(t, kind, "PASS" if r["PASS"] else "FAIL", r["notes"][:3])
            if kind == "changed":
                print("  増えた関係行:", len(r["added_relations"]), [f'{x["canonical_name"]}/{x["relation_type"]}/{x["relation_status"]}' for x in r["added_relations"]])
                if r["other_diffs"]: print("  その他の差分:", r["other_diffs"])
    allp = all(v["PASS"] for v in out.values())
    a.report.write_text(json.dumps({"ALL_PASS": allp, "results": out}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("ALL_PASS" if allp else "FAIL"); sys.exit(0 if allp else 1)

if __name__ == "__main__":
    main()
