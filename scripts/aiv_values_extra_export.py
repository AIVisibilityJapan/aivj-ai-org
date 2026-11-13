#!/usr/bin/env python3
"""白浜町・出雲市・和泉市の、出現率（総合）とネガティブ件数を書き出す（読み取り専用）。
あわせて、完成済み38件の同じ値も出して、導出規則の検証に使う。
実行: リポジトリ直下で  py scripts\\aiv_values_extra_export.py
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
OUT = REPO / "データ/private/06-STEP4作業/資源確認/出力" / f"追加値_{datetime.now():%Y%m%d_%H%M%S}"
EXTRA = ["MUNI_304018", "MUNI_322032", "MUNI_272191"]


def ro(p):
    c = sqlite3.connect(p.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    c.row_factory = sqlite3.Row
    return c


def main():
    OUT.mkdir(parents=True)
    a, p = ro(AP), ro(APA)
    ids = [r["municipality_id"] for r in json.loads(VAL.read_text(encoding="utf-8-sig"))] + EXTRA
    if "--all" in sys.argv:
        ids = sorted({r[0] for r in p.execute("select municipality_id from municipality_master")} | {r[0] for r in a.execute("select municipality_id from appearance_municipality")})
    rates, neg = [], []
    for mid in ids:
        for r in a.execute("select municipality_id, scope, scope_target_name, metric_type, appearance_count, valid_response_count, appearance_rate, value_status "
                           "from appearance_rate where municipality_id=? and (category_name is null or category_name='')", (mid,)):
            rates.append(dict(r))
        for r in p.execute("select municipality_id, negative_reason_count_total_raw, negative_reason_unique_exact_total, evaluations_with_negative "
                           "from municipality_negative_summary where municipality_id=?", (mid,)):
            neg.append(dict(r))
    for name, rows in (("01_rates_overall.csv", rates), ("02_negative.csv", neg)):
        with (OUT / name).open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print("rates:", len(rates), "negative:", len(neg), "／出力:", OUT)


if __name__ == "__main__":
    main()
