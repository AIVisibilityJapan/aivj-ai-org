#!/usr/bin/env python3
"""強み・弱みの分野（HIGH/LOW）とブロック母数の規則を探るための材料を書き出す（読み取り専用）。
38自治体＋白浜町・出雲市・和泉市について、カテゴリ別の出現率（全指標）と、ブロック／県の所属を出力する。
実行: リポジトリ直下で  py scripts\\aiv_values_explore.py [--all]
"""
from __future__ import annotations
import csv, json, sqlite3, sys
from datetime import datetime
from pathlib import Path

REPO = Path.cwd().resolve()
H = REPO / "データ/private/05-測定データ/AIV_NEW_PC_HANDOFF_20261105/01_AI_Visibility/01_正式成果物"
AP = H / "01_出現率/Report Mart v2.4/正式データ/01_appearance_rate_report_mart_v2_4_final_release.sqlite"
APA = H / "02_APA/Report Mart/正式データ/01_MART/apa_v1_report_mart.sqlite"
VAL = REPO / "データ/private/06-STEP4作業/資源確認/ツール写し/097__report_values_s1550_38.json"
OUT = REPO / "データ/private/06-STEP4作業/資源確認/出力" / f"値探索_{datetime.now():%Y%m%d_%H%M%S}"
EXTRA = {"MUNI_304018", "MUNI_322032", "MUNI_272191"}

def ro(p):
    c = sqlite3.connect(p.resolve().as_uri() + "?mode=ro&immutable=1", uri=True); c.row_factory = sqlite3.Row; return c

def main():
    OUT.mkdir(parents=True)
    truth = {r["municipality_id"]: r for r in json.loads(VAL.read_text(encoding="utf-8-sig"))}
    ids = list(truth) + sorted(EXTRA)
    a, p = ro(AP), ro(APA)
    if "--all" in sys.argv:  # 全国（APAの全自治体）を対象にする
        ids = sorted({r[0] for r in p.execute("select municipality_id from municipality_master")} | {r[0] for r in a.execute("select municipality_id from appearance_municipality")})
    rows = []
    q = ("select municipality_id, scope, scope_target_name, category_name, metric_type, appearance_count, valid_response_count, appearance_rate, value_status "
         "from appearance_rate where municipality_id=? and category_name<>''")
    for mid in ids:
        for r in a.execute(q, (mid,)):
            d = dict(r); d["truth_HIGH"] = truth[mid]["source_fields"]["HIGH_VALUE"] if mid in truth else ""
            d["truth_LOW"] = truth[mid]["source_fields"]["LOW_VALUE"] if mid in truth else ""
            d["municipality"] = truth[mid]["municipality"] if mid in truth else ""
            rows.append(d)
    with (OUT / "01_category_rates.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    # 所属: APA の自治体 → 出現率側の都道府県・ブロック（IDで結合）。結合できない自治体も出す
    apa = {r["municipality_id"]: dict(r) for r in p.execute("select * from municipality_master")}
    app = {r["municipality_id"]: dict(r) for r in a.execute("select * from appearance_municipality")}
    rk = {r[0]: r[1] for r in p.execute("select municipality_id, rank from rankings where evaluation_id='overall'")}
    mem = []
    for mid, m in apa.items():
        x = app.get(mid)
        mem.append({"municipality_id": mid, "name_apa": m["municipality_name"], "pref_apa": m["prefecture"],
                    "in_appearance": bool(x), "name_app": x["municipality_name"] if x else "", "pref_app": x["prefecture_name"] if x else "",
                    "block_app": x["region_block_name"] if x else "", "reporting": x["reporting_target_flag"] if x else "", "overall_rank": rk.get(mid, "")})
    with (OUT / "02_membership.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(mem[0])); w.writeheader(); w.writerows(mem)
    cats = [dict(r) for r in a.execute("select * from appearance_category")]
    (OUT / "03_categories.json").write_text(json.dumps(cats, ensure_ascii=False, indent=2), encoding="utf-8")
    print("category rows:", len(rows), "／所属:", len(mem), "／出力:", OUT)

if __name__ == "__main__":
    main()
