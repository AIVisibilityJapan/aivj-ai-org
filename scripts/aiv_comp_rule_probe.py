#!/usr/bin/env python3
"""比較表(COMP)の規則を探る材料を書き出す（読み取り専用）。
完成済み38自治体の COMP の相手自治体が、APA の municipality_comparisons のどの評価・結果・ラウンドに現れるかを出力する。
実行: リポジトリ直下で  py scripts\\aiv_comp_rule_probe.py
出力: データ/private/06-STEP4作業/資源確認/出力/COMP探索_<日時>/01_probe.csv, 02_eval_ids.csv, 03_summary.json
"""
from __future__ import annotations
import csv, json, re, sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path.cwd().resolve()
H = REPO / "データ/private/05-測定データ/AIV_NEW_PC_HANDOFF_20261105/01_AI_Visibility/01_正式成果物"
APA = H / "02_APA/Report Mart/正式データ/01_MART/apa_v1_report_mart.sqlite"
VAL = REPO / "データ/private/06-STEP4作業/資源確認/ツール写し/097__report_values_s1550_38.json"
OUT = REPO / "データ/private/06-STEP4作業/資源確認/出力" / f"COMP探索_{datetime.now():%Y%m%d_%H%M%S}"


def ro(p):
    c = sqlite3.connect(p.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    c.row_factory = sqlite3.Row
    return c


def split_name(s):
    m = re.match(r"^(.*)（(.*)）$", s or "")
    return (m.group(1), m.group(2)) if m else (s, "")


def main():
    OUT.mkdir(parents=True)
    truth = json.loads(VAL.read_text(encoding="utf-8-sig"))
    p = ro(APA)
    master = {r["municipality_id"]: (r["municipality_name"], r["prefecture"]) for r in p.execute("select * from municipality_master")}
    by_name = defaultdict(list)
    for mid, (n, pf) in master.items():
        by_name[(n, pf)].append(mid)
    rank = {}
    for r in p.execute("select municipality_id, evaluation_id, rank from rankings"):
        rank[(r["municipality_id"], r["evaluation_id"])] = r["rank"]
    eval_ids = [r[0] for r in p.execute("select distinct evaluation_id from rankings order by 1")]
    with (OUT / "02_eval_ids.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f); w.writerow(["evaluation_id"]); [w.writerow([e]) for e in eval_ids]
    rows = []
    for t in truth:
        mid = t["municipality_id"]; sf = t["source_fields"]
        for i in (1, 2, 3):
            label = sf[f"COMP_R{i}C1"]
            for c in (2, 3, 4):
                nm, pf = split_name(sf[f"COMP_R{i}C{c}"])
                oids = by_name.get((nm, pf), [])
                for oid in oids:
                    q = ("select evaluation_id, stage, round, result from municipality_comparisons "
                         "where municipality_id=? and opponent_id=?")
                    for r in p.execute(q, (mid, oid)):
                        rows.append({"municipality": t["municipality"], "row": i, "row_label": label, "col": c,
                                     "opponent": sf[f"COMP_R{i}C{c}"], "opponent_id": oid,
                                     "evaluation_id": r["evaluation_id"], "stage": r["stage"], "round": r["round"],
                                     "result": r["result"],
                                     "self_rank_in_eval": rank.get((mid, r["evaluation_id"]), ""),
                                     "opp_rank_in_eval": rank.get((oid, r["evaluation_id"]), ""),
                                     "self_overall_rank": rank.get((mid, "overall"), ""),
                                     "opp_overall_rank": rank.get((oid, "overall"), "")})
    with (OUT / "01_probe.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    cnt = Counter((r["row_label"] if r["row"] == 1 else "ジャンル行", r["evaluation_id"], r["result"]) for r in rows)
    (OUT / "03_summary.json").write_text(json.dumps(
        {"rows": len(rows), "eval_ids": eval_ids,
         "counts": [[*k, v] for k, v in sorted(cnt.items(), key=lambda kv: -kv[1])[:60]]},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print("probe rows:", len(rows), "／出力:", OUT)


if __name__ == "__main__":
    main()
