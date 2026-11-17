#!/usr/bin/env python3
"""R1 / T1（値取り出し）の設計のための確認（読み取り専用）。

確認すること（設計書 R1_T1_値取り出し_実装設計.md §8 の P1〜P4）
  P1 出現率の再現: 質問単位の表（appearance_question／appearance_question_municipality）から、
     Mart 自身の出現率（appearance_rate／appearance_dimension_rate）を再現できるか。
     再現できれば、Mart に無い「階層別の同行者・季節・旅程」を同じ規則で導出してよい根拠になる。
  P2 近接自治体の直接対戦: APA で、順位が近接する上位3・下位3の自治体と、直接の対戦記録があるか
     （競合分析の「理由」は、直接の対戦記録がある相手にしか付けられない）。
  P3 資源の件数の定義: municipality_asset_top5 の question_count が、出現記録（appearance_asset_occurrence）の
     「ユニーク質問数」「行数」のどちらと一致するか（サンプルの「言及回数」との対応を決める材料）。
  P5 直接対戦した相手のうち順位が近い上位3・下位3の、順位の離れ方と、理由欄の充足率。
  P6 資源の出現データの量（自治体あたりの資源数・出現行数）。
  P4 ネガティブの件数と分類の作業量: municipality_negative_summary の件数が negative_reasons の行数と一致するか、
     自治体あたりのユニークな理由文の数（分類の作業量の見積り）。

守ること
  - Mart は読み取り専用（mode=ro & immutable=1）。書き込み・移動・削除・保存し直しはしない。
  - 出力は新しいフォルダにだけ書く。外部送信・API 実行なし。値は数えるだけで、補完・推測はしない。

使い方（リポジトリ直下 C:\\dev\\aivj-ai-org で）:
  py scripts\\aiv_r1_t1_probe.py
  py scripts\\aiv_r1_t1_probe.py --only P1      （P1〜P4 のうち指定したものだけ。複数は --only P1 P2）
"""
from __future__ import annotations
import argparse, csv, json, os, re, sqlite3, statistics, sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path.cwd().resolve()
FORMAL = REPO / "データ/private/05-測定データ/AIV_FORMAL_ROOT_20261114/AI Visibility/01_正式成果物"
AP_DEFAULT = FORMAL / "01_出現率/Report Mart v2.4/正式データ/01_appearance_rate_report_mart_v2_4_final_release.sqlite"
APA_DEFAULT = FORMAL / "02_APA/Report Mart/正式データ/01_MART/apa_v1_report_mart.sqlite"
OUT_BASE = REPO / "データ/private/06-STEP4作業/資源確認/出力"
CUTOFF = 3  # formal_rank_cutoff（Mart の appearance_measurement に記録された値）
BAD_STATUS = re.compile(r"(reject|exclude|invalid|unresolved|non_?asset|gap|review|pending)", re.I)


def ro(p: Path) -> sqlite3.Connection:
    c = sqlite3.connect(p.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    c.row_factory = sqlite3.Row
    return c


def tables(con):
    return {r[0] for r in con.execute("select name from sqlite_master where type in ('table','view')")}


def write_csv(path: Path, rows: list[dict]):
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    keys = list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------- P1
def p1(a, out: Path, summary: dict):
    q = {}
    for r in a.execute("select question_id, scope, scope_target_id, category_id, traveler_type, season, itinerary from appearance_question"):
        q[r["question_id"]] = (r["scope"], r["scope_target_id"], r["category_id"], r["traveler_type"], r["season"], r["itinerary"])
    qm = defaultdict(list)
    for r in a.execute("select question_id, municipality_id, min_candidate_rank, resolution_status, measurement_origin from appearance_question_municipality"):
        qm[r["municipality_id"]].append((r["question_id"], r["min_candidate_rank"], r["resolution_status"], r["measurement_origin"]))
    st = Counter(x[2] for v in qm.values() for x in v)
    org = Counter(x[3] for v in qm.values() for x in v)
    rk = Counter(x[1] for v in qm.values() for x in v)
    summary["P1_distinct"] = {"resolution_status": dict(st), "measurement_origin": dict(org), "min_candidate_rank": {str(k): v for k, v in sorted(rk.items(), key=lambda kv: str(kv[0]))}}

    denom = Counter()  # (scope, target, cat) -> 質問数
    for qid, (sc, tg, cat, *_r) in q.items():
        denom[(sc, tg, cat)] += 1
        denom[(sc, tg, None)] += 1
        denom[("all_scopes", "__ALL_SCOPES__", cat)] += 1
        denom[("all_scopes", "__ALL_SCOPES__", None)] += 1

    def match(qid, scope, target, cat):
        sc, tg, c, *_r = q[qid]
        if scope != "all_scopes" and (sc != scope or tg != target):
            return False
        return cat is None or c == cat

    variants = {
        "A_rank<=3": lambda x: x[1] is not None and x[1] <= CUTOFF,
        "C_rank<=3_かつ状態が除外系でない": lambda x: x[1] is not None and x[1] <= CUTOFF and not BAD_STATUS.search(str(x[2] or "")),
    }
    ok = {k: 0 for k in variants}
    n = 0
    na = 0
    denom_ok = 0
    mism = {k: [] for k in variants}
    rows = a.execute(
        "select municipality_id, scope, scope_target_id, category_id, metric_type, appearance_count, valid_response_count "
        "from appearance_rate where metric_type in ('overall_scope_rate','category_scope_rate','overall_all_scopes_rate','category_all_scopes_rate')")
    for r in rows:
        mid, sc, tg, cat = r["municipality_id"], r["scope"], r["scope_target_id"], (r["category_id"] or None)
        if tg == "__NOT_APPLICABLE__" or r["appearance_count"] is None:
            na += 1  # 地域ブロック対象外（北海道・沖縄）など。Mart 自身が値を持たない行は比較しない
            continue
        n += 1
        d = denom.get((sc, tg, cat), 0)
        if d == r["valid_response_count"]:
            denom_ok += 1
        for k, f in variants.items():
            qs = {x[0] for x in qm.get(mid, []) if f(x) and match(x[0], sc, tg, cat)}
            if len(qs) == r["appearance_count"]:
                ok[k] += 1
            elif len(mism[k]) < 2000:
                mism[k].append({"variant": k, "municipality_id": mid, "scope": sc, "scope_target_id": tg, "category_id": cat or "",
                                "metric_type": r["metric_type"], "mart_count": r["appearance_count"], "derived_count": len(qs)})
    summary["P1_rate_reproduction"] = {"rate_rows_compared": n, "rows_skipped_not_applicable": na, "denominator_match": denom_ok,
                                       "numerator_match": ok, "note": "numerator_match は appearance_count と一致した行数（変種ごと）"}
    best = max(ok, key=ok.get) if ok else None
    write_csv(out / "01_p1_mismatch_best_variant.csv", mism.get(best, []) if best else [])

    # 同行者・季節・旅程（全体基準）の再現
    dim_ok = dim_n = 0
    dim_mism = []
    f = variants[best] if best else None
    if f and "appearance_dimension_rate" in tables(a):
        idx = {"traveler": 3, "season": 4, "itinerary": 5}
        for r in a.execute("select municipality_id, dimension_type, dimension_value, appearance_count, valid_response_count from appearance_dimension_rate"):
            i = idx.get(r["dimension_type"])
            if i is None:
                continue
            dim_n += 1
            qs = {x[0] for x in qm.get(r["municipality_id"], []) if f(x) and q[x[0]][i] == r["dimension_value"]}
            tot = sum(1 for v in q.values() if v[i] == r["dimension_value"])
            if len(qs) == r["appearance_count"] and tot == r["valid_response_count"]:
                dim_ok += 1
            elif len(dim_mism) < 100:
                dim_mism.append({"municipality_id": r["municipality_id"], "dimension": r["dimension_type"], "value": r["dimension_value"],
                                 "mart_count": r["appearance_count"], "derived_count": len(qs), "mart_denominator": r["valid_response_count"], "derived_denominator": tot})
    summary["P1_dimension_reproduction"] = {"best_variant": best, "rows": dim_n, "match": dim_ok}
    write_csv(out / "01_p1_dimension_mismatch.csv", dim_mism)


# ---------------------------------------------------------------- P2
def p2(p, out: Path, summary: dict):
    rank = defaultdict(dict)  # eval -> {rank: mid}
    rk = {}
    for r in p.execute("select municipality_id, evaluation_id, rank from rankings"):
        rank[r["evaluation_id"]][int(r["rank"])] = r["municipality_id"]
        rk[(r["municipality_id"], r["evaluation_id"])] = int(r["rank"])
    pairs = defaultdict(set)
    for r in p.execute("select evaluation_id, municipality_a_id, municipality_b_id from comparisons"):
        pairs[r["evaluation_id"]].add((r["municipality_a_id"], r["municipality_b_id"]))
        pairs[r["evaluation_id"]].add((r["municipality_b_id"], r["municipality_a_id"]))
    rows = []
    for ev, d in sorted(rank.items()):
        up = up_cov = dn = dn_cov = full = munis = 0
        for rkv, mid in d.items():
            munis += 1
            all_ok = True
            for off in (-3, -2, -1, 1, 2, 3):
                nb = d.get(rkv + off)
                if nb is None:
                    continue
                cov = (mid, nb) in pairs[ev]
                if off < 0:
                    up += 1; up_cov += cov
                else:
                    dn += 1; dn_cov += cov
                all_ok &= cov
            full += all_ok
        rows.append({"evaluation_id": ev, "municipalities": munis, "upper_pairs": up, "upper_with_direct_comparison": up_cov,
                     "lower_pairs": dn, "lower_with_direct_comparison": dn_cov, "municipalities_all_neighbors_covered": full,
                     "upper_share": round(up_cov / up, 4) if up else None, "lower_share": round(dn_cov / dn, 4) if dn else None})
    write_csv(out / "02_p2_pair_coverage_by_evaluation.csv", rows)
    tot = lambda k: sum(r[k] for r in rows)
    summary["P2_pair_coverage"] = {"upper_share": round(tot("upper_with_direct_comparison") / max(1, tot("upper_pairs")), 4),
                                   "lower_share": round(tot("lower_with_direct_comparison") / max(1, tot("lower_pairs")), 4),
                                   "note": "近接上位3・下位3（順位±1〜3）のうち、直接の対戦記録がある割合。評価区分ごとは 02_*.csv"}


# ---------------------------------------------------------------- P3
def p3(a, out: Path, summary: dict):
    t = tables(a)
    if "municipality_asset_top5" not in t or "appearance_asset_occurrence" not in t:
        summary["P3"] = "対象の表が無い"
        return
    occ_q = defaultdict(set)
    occ_n = Counter()
    for r in a.execute("select municipality_id, metric_scope, asset_id, question_id from appearance_asset_occurrence"):
        k = (r["municipality_id"], r["metric_scope"], r["asset_id"])
        occ_q[k].add(r["question_id"])
        occ_n[k] += 1
    n = eq_q = eq_n = 0
    rows = []
    for r in a.execute("select municipality_id, metric_scope, asset_id, question_count from municipality_asset_top5"):
        k = (r["municipality_id"], r["metric_scope"], r["asset_id"])
        n += 1
        eq_q += (len(occ_q.get(k, ())) == r["question_count"])
        eq_n += (occ_n.get(k, 0) == r["question_count"])
        if len(rows) < 50 and len(occ_q.get(k, ())) != r["question_count"]:
            rows.append({"municipality_id": r["municipality_id"], "metric_scope": r["metric_scope"], "asset_id": r["asset_id"],
                         "question_count": r["question_count"], "occurrence_unique_questions": len(occ_q.get(k, ())), "occurrence_rows": occ_n.get(k, 0)})
    summary["P3_asset_counts"] = {"top5_rows": n, "question_count==unique_questions": eq_q, "question_count==occurrence_rows": eq_n,
                                  "metric_scope_values": [r[0] for r in a.execute("select distinct metric_scope from municipality_asset_top5")]}
    write_csv(out / "03_p3_asset_count_mismatch.csv", rows)


# ---------------------------------------------------------------- P4
def p4(p, out: Path, summary: dict):
    summ = {r[0]: r[1] for r in p.execute("select municipality_id, negative_reason_count_total_raw from municipality_negative_summary")}
    cnt = {r[0]: r[1] for r in p.execute(
        "select municipality_id, count(*) from negative_reasons where negative_reason is not null and trim(negative_reason)<>'' group by municipality_id")}
    uniq = {r[0]: r[1] for r in p.execute(
        "select municipality_id, count(distinct normalized_negative_reason) from negative_reasons "
        "where normalized_negative_reason is not null and trim(normalized_negative_reason)<>'' group by municipality_id")}
    same = sum(1 for m, v in summ.items() if cnt.get(m, 0) == v)
    u = sorted(uniq.values())
    summary["P4_negative"] = {"municipalities": len(summ), "summary_equals_row_count": same,
                              "unique_normalized_reasons_per_municipality": {"min": u[0] if u else None, "median": statistics.median(u) if u else None,
                                                                              "p90": u[int(len(u) * 0.9)] if u else None, "max": u[-1] if u else None},
                              "note": "unique は分類の作業量の目安（理由文の種類数）。正規化後の文字列単位"}
    write_csv(out / "04_p4_negative_per_municipality.csv",
              [{"municipality_id": m, "summary_total_raw": summ[m], "negative_rows": cnt.get(m, 0), "unique_normalized_reasons": uniq.get(m, 0)}
               for m in sorted(summ)])


# ---------------------------------------------------------------- P5
def p5(p, out: Path, summary: dict):
    """直接対戦した相手のうち、順位が近い上位3・下位3を取るとき、順位の離れ方はどれくらいか。"""
    rank = defaultdict(dict)
    for r in p.execute("select municipality_id, evaluation_id, rank from rankings"):
        rank[r["evaluation_id"]][r["municipality_id"]] = int(r["rank"])
    opp = defaultdict(lambda: defaultdict(set))
    for r in p.execute("select evaluation_id, municipality_a_id, municipality_b_id from comparisons"):
        opp[r["evaluation_id"]][r["municipality_a_id"]].add(r["municipality_b_id"])
        opp[r["evaluation_id"]][r["municipality_b_id"]].add(r["municipality_a_id"])
    rows = []
    for ev, rk in sorted(rank.items()):
        pop = len(rk)
        n_up = n_dn = ok_up = ok_dn = 0
        d_up, d_dn, nopp = [], [], []
        for mid, r0 in rk.items():
            ranks = sorted(rk[o] for o in opp[ev].get(mid, ()) if o in rk)
            nopp.append(len(ranks))
            above = [x for x in ranks if x < r0][::-1]  # 近い順
            below = [x for x in ranks if x > r0]
            if r0 > 3:
                n_up += 1
                if len(above) >= 3:
                    ok_up += 1; d_up.append(r0 - above[2])
            if r0 <= pop - 3:
                n_dn += 1
                if len(below) >= 3:
                    ok_dn += 1; d_dn.append(below[2] - r0)
        def q(v, f):
            v = sorted(v)
            return v[min(len(v) - 1, int(len(v) * f))] if v else None
        rows.append({"evaluation_id": ev, "population": pop, "opponents_median": statistics.median(nopp) if nopp else None,
                     "above_eligible": n_up, "above_with_3_opponents": ok_up, "above_3rd_distance_median": statistics.median(d_up) if d_up else None,
                     "above_3rd_distance_p90": q(d_up, 0.9), "above_3rd_distance_max": max(d_up) if d_up else None,
                     "below_eligible": n_dn, "below_with_3_opponents": ok_dn, "below_3rd_distance_median": statistics.median(d_dn) if d_dn else None,
                     "below_3rd_distance_p90": q(d_dn, 0.9), "below_3rd_distance_max": max(d_dn) if d_dn else None})
    write_csv(out / "05_p5_nearest_direct_opponents_by_evaluation.csv", rows)
    ov = [r for r in rows if r["evaluation_id"] == "overall"]
    summary["P5_nearest_direct_opponents"] = {"overall": ov[0] if ov else None, "note": "評価区分ごとは 05_*.csv。distance は3番目に近い直接対戦相手との順位差"}
    # 理由欄が空でない比率（全対戦の行数に対する）
    tot = p.execute("select count(*) from municipality_comparisons").fetchone()[0]
    nz = {c: p.execute(f"select count(*) from municipality_comparisons where trim(coalesce({c},''))<>''").fetchone()[0]
          for c in ("recommended_reason", "not_recommended_reason", "self_positive_reason", "opponent_positive_reason")}
    summary["P5_reason_fill"] = {"rows": tot, "non_empty": nz}


# ---------------------------------------------------------------- P6
def p6(a, out: Path, summary: dict):
    """資源の出現データの量（自治体あたり）。"""
    per = defaultdict(lambda: [set(), 0])
    for r in a.execute("select municipality_id, asset_id, question_id from appearance_asset_occurrence"):
        per[r["municipality_id"]][0].add(r["asset_id"]); per[r["municipality_id"]][1] += 1
    nas = sorted(len(v[0]) for v in per.values())
    noc = sorted(v[1] for v in per.values())
    total_m = a.execute("select count(*) from appearance_municipality where reporting_target_flag in (1,'1','true','TRUE','True')").fetchone()[0]
    f = lambda v, x: v[min(len(v) - 1, int(len(v) * x))] if v else None
    summary["P6_asset_volume"] = {"municipalities_with_any_asset": len(per), "reporting_targets": total_m,
                                  "assets_per_municipality": {"median": f(nas, .5), "p90": f(nas, .9), "max": nas[-1] if nas else None,
                                                              "ge3": sum(x >= 3 for x in nas), "ge10": sum(x >= 10 for x in nas)},
                                  "occurrences_per_municipality": {"median": f(noc, .5), "p90": f(noc, .9), "max": noc[-1] if noc else None,
                                                                   "ge30": sum(x >= 30 for x in noc)}}
    write_csv(out / "06_p6_asset_volume_per_municipality.csv",
              [{"municipality_id": m, "distinct_assets": len(v[0]), "occurrence_rows": v[1]} for m, v in sorted(per.items())])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--appearance", default=str(AP_DEFAULT))
    ap.add_argument("--apa", default=str(APA_DEFAULT))
    ap.add_argument("--only", nargs="*", default=["P1", "P2", "P3", "P4", "P5", "P6"], choices=["P1", "P2", "P3", "P4", "P5", "P6"])
    a_ = ap.parse_args()
    out = OUT_BASE / f"R1_T1確認_{datetime.now():%Y%m%d_%H%M%S}_{os.getpid()}"
    out.mkdir(parents=True, exist_ok=False)  # 既存フォルダには触らない
    summary = {"only": a_.only, "appearance_mart": a_.appearance, "apa_mart": a_.apa}
    if {"P1", "P3", "P6"} & set(a_.only):
        a = ro(Path(a_.appearance))
        if "P1" in a_.only:
            p1(a, out, summary)
        if "P3" in a_.only:
            p3(a, out, summary)
        if "P6" in a_.only:
            p6(a, out, summary)
        a.close()
    if {"P2", "P4", "P5"} & set(a_.only):
        p = ro(Path(a_.apa))
        if "P2" in a_.only:
            p2(p, out, summary)
        if "P4" in a_.only:
            p4(p, out, summary)
        if "P5" in a_.only:
            p5(p, out, summary)
        p.close()
    (out / "00_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("出力:", out)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
