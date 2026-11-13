#!/usr/bin/env python3
"""Mart から無償レポートの値を導く規則の検証（読み取り専用）。
完成済み38自治体の report_values（正解）と、Mart から導いた値を比べ、項目ごとの一致数を出す。
一致しない項目は規則が未確定なので、その項目は3市町の試験に使わない。
実行: リポジトリ直下で  py scripts\\aiv_values_derive_check.py
"""
from __future__ import annotations
import csv, json, sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path.cwd().resolve()
H = REPO / "データ/private/05-測定データ/AIV_NEW_PC_HANDOFF_20261105/01_AI_Visibility/01_正式成果物"
AP = H / "01_出現率/Report Mart v2.4/正式データ/01_appearance_rate_report_mart_v2_4_final_release.sqlite"
APA = H / "02_APA/Report Mart/正式データ/01_MART/apa_v1_report_mart.sqlite"
VAL = REPO / "データ/private/06-STEP4作業/資源確認/ツール写し/097__report_values_s1550_38.json"
OUT = REPO / "データ/private/06-STEP4作業/資源確認/出力" / f"値導出検証_{datetime.now():%Y%m%d_%H%M%S}"

def ro(p):
    c = sqlite3.connect(p.resolve().as_uri() + "?mode=ro&immutable=1", uri=True); c.row_factory = sqlite3.Row; return c

def pct(x): return f"{x*100:.1f}%"

def main():
    OUT.mkdir(parents=True)
    truth = {r["municipality_id"]: r for r in json.loads(VAL.read_text(encoding="utf-8-sig"))}
    a, p = ro(AP), ro(APA)
    muni = {r["municipality_id"]: dict(r) for r in a.execute("select * from appearance_municipality")}
    apa_ids = {r[0] for r in p.execute("select municipality_id from municipality_master")}
    rank = {r[0]: r[1] for r in p.execute("select municipality_id, rank from rankings where evaluation_id='overall'")}
    neg = {r[0]: r[1] for r in p.execute("select municipality_id, negative_reason_count_total_raw from municipality_negative_summary")}
    # 地域・県内順位: 同じブロック／県の APA 対象自治体を overall 順位で並べる
    by_block, by_pref = defaultdict(list), defaultdict(list)
    for mid in apa_ids:
        m = muni.get(mid)
        if m and mid in rank:
            by_block[m["region_block_name"]].append((rank[mid], mid)); by_pref[m["prefecture_name"]].append((rank[mid], mid))
    for d in (by_block, by_pref):
        for k in d: d[k].sort()
    rates = defaultdict(dict)
    for r in a.execute("select municipality_id, scope, scope_target_name, appearance_rate, value_status from appearance_rate where metric_type='overall_scope_rate'"):
        rates[r["municipality_id"]][r["scope"]] = r["appearance_rate"]
    cat = defaultdict(dict)
    for r in a.execute("select municipality_id, category_name, appearance_rate from appearance_rate where metric_type='category_all_scopes_rate'"):
        cat[r["municipality_id"]][r["category_name"]] = r["appearance_rate"]
    fields = ["national_rank", "region_rank", "region_population", "prefecture_rank", "prefecture_population",
              "national_rate", "region_rate", "prefecture_rate", "negative_count", "HIGH_VALUE", "LOW_VALUE"]
    ok = {f: 0 for f in fields}; bad = []
    for mid, t in truth.items():
        m = muni[mid]; blk = by_block[m["region_block_name"]]; prf = by_pref[m["prefecture_name"]]
        mine = {
            "national_rank": rank.get(mid),
            "region_rank": [x[1] for x in blk].index(mid) + 1 if mid in [x[1] for x in blk] else None,
            "region_population": len(blk),
            "prefecture_rank": [x[1] for x in prf].index(mid) + 1 if mid in [x[1] for x in prf] else None,
            "prefecture_population": len(prf),
            "national_rate": pct(rates[mid].get("national", 0)), "region_rate": pct(rates[mid].get("region_block", 0)),
            "prefecture_rate": pct(rates[mid].get("prefecture", 0)), "negative_count": neg.get(mid),
        }
        c = cat[mid]
        if c:
            mx, mn = max(c.values()), min(c.values())
            hi = [k for k, v in c.items() if v == mx]; lo = [k for k, v in c.items() if v == mn]
            mine["HIGH_VALUE"] = "全カテゴリ同率" if mx == mn else "／".join(hi)
            mine["LOW_VALUE"] = "全カテゴリ同率" if mx == mn else "／".join(lo)
        tv = dict(t); tv["HIGH_VALUE"] = t["source_fields"]["HIGH_VALUE"]; tv["LOW_VALUE"] = t["source_fields"]["LOW_VALUE"]
        for f in fields:
            if str(mine.get(f)) == str(tv.get(f)): ok[f] += 1
            else: bad.append({"municipality": t["municipality"], "field": f, "truth": tv.get(f), "derived": mine.get(f)})
    n = len(truth)
    res = {"municipalities": n, "match": {f: f"{ok[f]}/{n}" for f in fields}}
    (OUT / "00_summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    with (OUT / "01_mismatch.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["municipality", "field", "truth", "derived"]); w.writeheader(); w.writerows(bad)
    print(json.dumps(res, ensure_ascii=False, indent=2)); print("出力:", OUT)

if __name__ == "__main__":
    main()
