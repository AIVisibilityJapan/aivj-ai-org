#!/usr/bin/env python3
"""比較表(COMP)の分野行の規則を探る材料を書き出す（読み取り専用）。
38自治体＋白浜町・出雲市・和泉市について、APA の全評価区分の順位と「各区分で直前の3自治体」を出力する。
実行: リポジトリ直下で  py scripts\\aiv_comp_rule_probe2.py
"""
from __future__ import annotations
import csv, json, sqlite3, sys
from datetime import datetime
from pathlib import Path

REPO = Path.cwd().resolve()
H = REPO / "データ/private/05-測定データ/AIV_NEW_PC_HANDOFF_20261105/01_AI_Visibility/01_正式成果物"
APA = H / "02_APA/Report Mart/正式データ/01_MART/apa_v1_report_mart.sqlite"
VAL = REPO / "データ/private/06-STEP4作業/資源確認/ツール写し/097__report_values_s1550_38.json"
OUT = REPO / "データ/private/06-STEP4作業/資源確認/出力" / f"COMP探索2_{datetime.now():%Y%m%d_%H%M%S}"
EXTRA = ["MUNI_304018", "MUNI_322032", "MUNI_272191"]


def main():
    OUT.mkdir(parents=True)
    c = sqlite3.connect(APA.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    truth = {r["municipality_id"]: r for r in json.loads(VAL.read_text(encoding="utf-8-sig"))}
    ids = list(truth) + EXTRA
    if "--all" in sys.argv:
        ids = [r[0] for r in c.execute("select municipality_id from municipality_master")]
    name = {r[0]: f"{r[1]}（{r[2]}）" for r in c.execute("select municipality_id, municipality_name, prefecture from municipality_master")}
    by_eval = {}
    for mid, ev, rk in c.execute("select municipality_id, evaluation_id, rank from rankings"):
        by_eval.setdefault(ev, {})[int(rk)] = mid
    rank = {(m, e): r for e, d in by_eval.items() for r, m in d.items()}
    rows = []
    for mid in ids:
        t = truth.get(mid)
        for ev, d in by_eval.items():
            rk = rank.get((mid, ev))
            if rk is None:
                continue
            above = [name.get(d.get(rk - i), "") for i in (3, 2, 1)]
            top4 = [name.get(d.get(i), "") for i in (1, 2, 3, 4)]
            rows.append({"municipality_id": mid, "municipality": name[mid], "evaluation_id": ev, "rank": rk,
                         "population": len(d), "above1": above[0], "above2": above[1], "above3": above[2],
                         "top1": top4[0], "top2": top4[1], "top3": top4[2], "top4": top4[3],
                         "truth_row2_label": t["source_fields"]["COMP_R2C1"] if t else "",
                         "truth_row3_label": t["source_fields"]["COMP_R3C1"] if t else "",
                         "truth_row2": "|".join(t["source_fields"][f"COMP_R2C{k}"] for k in (2, 3, 4)) if t else "",
                         "truth_row3": "|".join(t["source_fields"][f"COMP_R3C{k}"] for k in (2, 3, 4)) if t else ""})
    with (OUT / "01_ranks_by_eval.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print("rows:", len(rows), "／評価区分:", sorted(by_eval), "／出力:", OUT)


if __name__ == "__main__":
    main()
