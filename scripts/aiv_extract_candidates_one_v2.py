#!/usr/bin/env python3
"""観光資源の候補抽出（S1）を 1 自治体について行う。完全読み取り専用。
測定の原文（APA の自分側の理由・出現率の候補）から、具体名の候補を集め、Common Asset（マスター／別名）との照合結果を付ける。
分類（採用／不採用）はしない。根拠確認（AI-03-04）と独立監査（AI-06-05）の入力を作るだけ。
実行: リポジトリ直下で  py scripts\\aiv_extract_candidates_one.py 和泉市 大阪府
"""
from __future__ import annotations
import csv, json, sqlite3, sys, unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

csv.field_size_limit(10**9)
R = Path(__file__).resolve().parents[1]
BASE = R / "データ/private/05-測定データ/AIV_NEW_PC_HANDOFF_20261105/01_AI_Visibility/01_正式成果物"
AP = BASE / "01_出現率/Report Mart v2.4/正式データ/01_appearance_rate_report_mart_v2_4_final_release.sqlite"
APA = BASE / "02_APA/Report Mart/正式データ/01_MART/apa_v1_report_mart.sqlite"
W = R / "データ/private/06-STEP4作業/資源確認"
IN = W / "入力"
F = {"gate": "gate_municipality_status_v1_1_8.csv", "selector": "diagnostic_selector_v1_5_51_formal_slots_common_v1_1_31_apa_mapping_v1_1_30.csv",
     "master": "common_tourism_asset_master_v1_1_31.csv", "alias": "common_tourism_asset_alias_v1_1_24.csv", "relation": "common_asset_municipality_relation_v1_1_31.csv"}

def bare(m): return m[5:] if (m or "").startswith("MUNI_") else (m or "")
def nk(s): return "".join(unicodedata.normalize("NFKC", s or "").split()).casefold()
def rcsv(p):
    with p.open("r", encoding="utf-8-sig", newline="") as f: return list(csv.DictReader(f))
def ro(p):
    c = sqlite3.connect(p.resolve().as_uri() + "?mode=ro&immutable=1", uri=True); c.row_factory = sqlite3.Row; return c
def stat(ps): return {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in ps}
def wcsv(p, rows, fields=None):
    fields = fields or (list(rows[0]) if rows else ["(なし)"])
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader(); w.writerows(rows)

def main():
    if len(sys.argv) != 3: raise SystemExit("usage: aiv_extract_candidates_one.py 自治体名 都道府県")
    name, pref = sys.argv[1], sys.argv[2]
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    srcs = [AP, APA] + [IN / v for v in F.values()]
    before = stat(srcs)
    t = {k: rcsv(IN / v) for k, v in F.items()}
    hit = [r for r in t["gate"] if r["municipality_name"] == name and r["prefecture"] == pref]
    if len(hit) != 1: raise SystemExit(f"自治体が一意に決まりません: {name} {pref} ({len(hit)})")
    mid = hit[0]["municipality_id"]
    out = W / "出力" / f"候補抽出_{name}_{datetime.now():%Y%m%d_%H%M%S}"
    out.mkdir(parents=True)
    master = {r["asset_id"]: r for r in t["master"]}
    by_key = defaultdict(list)
    for r in t["master"]: by_key[nk(r["canonical_name"])].append(r["asset_id"])
    for r in t["alias"]: by_key[nk(r["alias"])].append(r["asset_id"])
    rel = defaultdict(list)
    for r in t["relation"]: rel[r["asset_id"]].append(r)
    def lookup(text):
        ids = sorted(set(by_key.get(nk(text), [])))
        d = []
        for a in ids:
            m = master.get(a, {}); mine = [x for x in rel.get(a, []) if bare(x["municipality_id"]) == bare(mid)]
            d.append(f'{a}|{m.get("canonical_name","")}|{m.get("verification_status","")}/{m.get("asset_status","")}|自分との関係=' + (",".join(x["relation_type"] for x in mine) or "なし"))
        return ids, " ; ".join(d)
    # 0) Gate と selector
    sel = sorted([r for r in t["selector"] if r["municipality_id"] == mid], key=lambda r: int(r["display_slot"]))
    wcsv(out / "00_gate_selector.csv", [{"item": "gate", **hit[0]}] + [{"item": f"slot{r['display_slot']}", **r} for r in sel])
    # 1) 出現率の候補（原文のまま。rank 1–5）
    ap = ro(AP)
    cand = [dict(r) for r in ap.execute(
        "select candidate_row_id, candidate_rank, rank_class, candidate_name, candidate_type, question_id, question_text, category_id, scope, "
        "original_municipality_id, resolved_municipality_id, context_municipality_id, final_resolution_status, original_classification, resolution_method, "
        "asset_id, canonical_asset_name, active_asset_flag from appearance_candidate_resolution "
        "where original_municipality_id=? or resolved_municipality_id=? or context_municipality_id=?", (mid, mid, mid))]
    for c in cand:
        ids, desc = lookup(c["candidate_name"]); c["common_match_ids"] = ";".join(ids); c["common_match_detail"] = desc
    wcsv(out / "01_appearance_candidates_raw.csv", cand)
    agg = defaultdict(lambda: {"questions": set(), "best_rank": 99, "statuses": set()})
    for c in cand:
        a = agg[c["candidate_name"]]; a["questions"].add(c["question_id"]); a["statuses"].add(c["final_resolution_status"])
        try: a["best_rank"] = min(a["best_rank"], int(c["candidate_rank"]))
        except Exception: pass
    rows = []
    for n, a in agg.items():
        ids, desc = lookup(n)
        rows.append({"candidate_text": n, "question_count": len(a["questions"]), "best_rank": a["best_rank"], "statuses": "/".join(sorted(a["statuses"])),
                     "in_common_asset": bool(ids), "common_match_detail": desc})
    rows.sort(key=lambda r: (-r["question_count"], r["best_rank"]))
    wcsv(out / "02_appearance_candidates_summary.csv", rows)
    wcsv(out / "03_appearance_top5_and_missing.csv",
         [{"kind": "top5", **dict(r)} for r in ap.execute("select * from municipality_asset_top5 where municipality_id=?", (mid,))] +
         [{"kind": "missing_reason", **dict(r)} for r in ap.execute("select * from municipality_asset_missing_reason where municipality_id=?", (mid,))])
    ap.close()
    # 2) APA: 自分側の勝ち理由の原文と、資源の言及
    pa = ro(APA)
    wins = [dict(r) for r in pa.execute(
        "select evaluation_id, comparison_id, stage, round, opponent_id, opponent_name, result, recommended_reason, self_positive_reason, source_path "
        "from municipality_comparisons where municipality_id=? and result='WIN' and coalesce(self_positive_reason,'')<>'' order by evaluation_id, comparison_id", (mid,))]
    wcsv(out / "04_apa_self_win_reasons.csv", wins)
    men = [dict(r) for r in pa.execute(
        "select comparison_id, evaluation_id, canonical_resource_name, resource_name_raw, resource_type, relation_type, verification_status, resource_tier, result, reason_type "
        "from apa_self_resource_mentions where municipality_id=?", (mid,))]
    for m in men:
        ids, desc = lookup(m["resource_name_raw"] or m["canonical_resource_name"]); m["common_match_ids"] = ";".join(ids); m["common_match_detail"] = desc
    wcsv(out / "05_apa_self_resource_mentions.csv", men)
    g = defaultdict(lambda: {"n": 0, "wins": 0, "types": set()})
    for m in men:
        k = m["resource_name_raw"] or m["canonical_resource_name"]; g[k]["n"] += 1; g[k]["wins"] += (m["result"] == "WIN"); g[k]["types"].add(m["resource_type"] or "")
    srows = []
    for k, v in g.items():
        ids, desc = lookup(k)
        srows.append({"resource_text": k, "mentions": v["n"], "win_mentions": v["wins"], "types": "/".join(sorted(v["types"])), "in_common_asset": bool(ids), "common_match_detail": desc})
    srows.sort(key=lambda r: (-r["win_mentions"], -r["mentions"]))
    wcsv(out / "06_apa_self_resource_summary.csv", srows)
    pa.close()
    # 3) 現行 Common Asset の関係（この自治体に結び付く資産）
    mine = []
    for r in t["relation"]:
        if bare(r["municipality_id"]) == bare(mid):
            m = master.get(r["asset_id"], {})
            mine.append({"asset_id": r["asset_id"], "canonical_name": m.get("canonical_name", ""), "relation_type": r["relation_type"], "relation_status": r.get("relation_status", ""),
                         "verification_status": r.get("verification_status", ""), "asset_status": m.get("asset_status", "")})
    wcsv(out / "07_common_asset_relations.csv", mine)
    after = stat(srcs)
    summary = {"municipality": name, "municipality_id": mid, "gate": hit[0]["decision_reason"], "report_generation_allowed": hit[0]["report_generation_allowed"],
               "appearance_candidate_rows": len(cand), "appearance_distinct_candidates": len(rows), "apa_self_win_reasons": len(wins),
               "apa_distinct_self_resources": len(srows), "common_asset_relations": len(mine),
               "source_files_changed": [k for k in before if before[k] != after[k]], "classification_done": False}
    (out / "08_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2)); print("出力:", out)

if __name__ == "__main__":
    main()
