#!/usr/bin/env python3
"""R1 / T1 再現ゲートの既知の例外 4 行の原因調査（読み取り専用）。

P1 で、出現率 Mart の値と質問単位の表からの再導出が 1 件ずれた 4 行
  MUNI_194298 / prefecture P19 / 全体・PUR_08、MUNI_412015 / prefecture P41 / 全体・PUR_08
について、ずれた質問を特定し、原因の候補（順位・状態・出所・重複・範囲の違い）を出す。

守ること: Mart は読み取り専用（mode=ro&immutable=1）。新しいフォルダにだけ書く。外部送信・API 実行なし。
使い方（C:\\dev\\aivj-ai-org で）:  py scripts\\aiv_r1_p7_exception_probe.py
"""
from __future__ import annotations
import argparse, csv, json, os, sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path.cwd().resolve()
FORMAL = REPO / "データ/private/05-測定データ/AIV_FORMAL_ROOT_20261114/AI Visibility/01_正式成果物"
AP_DEFAULT = FORMAL / "01_出現率/Report Mart v2.4/正式データ/01_appearance_rate_report_mart_v2_4_final_release.sqlite"
OUT_BASE = REPO / "データ/private/06-STEP4作業/資源確認/出力"
TARGETS = [("MUNI_194298", "P19"), ("MUNI_412015", "P41")]
CUTOFF = 3


def ro(p: Path):
    c = sqlite3.connect(p.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    c.row_factory = sqlite3.Row
    return c


def write_csv(path: Path, rows):
    if not rows:
        path.write_text("", encoding="utf-8-sig"); return
    keys = []
    for r in rows:
        for k in r:
            if k not in keys: keys.append(k)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)


def cols(con, t):
    return [r[1] for r in con.execute(f"pragma table_info({t})")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--appearance", default=str(AP_DEFAULT))
    a_ = ap.parse_args()
    out = OUT_BASE / f"R1_例外4行調査_{datetime.now():%Y%m%d_%H%M%S}_{os.getpid()}"
    out.mkdir(parents=True, exist_ok=False)
    a = ro(Path(a_.appearance))
    s = {"columns": {t: cols(a, t) for t in ("appearance_rate", "appearance_question", "appearance_question_municipality", "appearance_municipality")}}
    rate_rows, qm_rows = [], []
    for mid, pref in TARGETS:
        info = {}
        # 1) Mart の率の行（全列）
        for r in a.execute("select * from appearance_rate where municipality_id=? and scope='prefecture' and scope_target_id=? "
                           "and metric_type in ('overall_scope_rate','category_scope_rate') and coalesce(category_id,'') in ('','PUR_08')", (mid, pref)):
            rate_rows.append(dict(r))
        # 2) その自治体の質問単位の行（全列）に質問の属性を付ける
        rows = [dict(r) for r in a.execute(
            "select m.*, q.scope as q_scope, q.scope_target_id as q_target, q.category_id as q_category "
            "from appearance_question_municipality m join appearance_question q on q.question_id=m.question_id where m.municipality_id=?", (mid,))]
        info["qm_rows_total"] = len(rows)
        in_scope = [r for r in rows if r["q_scope"] == "prefecture" and r["q_target"] == pref]
        info["rows_in_scope"] = len(in_scope)
        info["distinct_questions_in_scope"] = len({r["question_id"] for r in in_scope})
        info["rank_counter_in_scope"] = dict(Counter(str(r["min_candidate_rank"]) for r in in_scope))
        info["status_counter_rank_le3_in_scope"] = dict(Counter(str(r.get("resolution_status")) for r in in_scope if r["min_candidate_rank"] is not None and r["min_candidate_rank"] <= CUTOFF))
        info["origin_counter_rank_le3_in_scope"] = dict(Counter(str(r.get("measurement_origin")) for r in in_scope if r["min_candidate_rank"] is not None and r["min_candidate_rank"] <= CUTOFF))
        dup = Counter(r["question_id"] for r in in_scope)
        info["duplicate_question_rows_in_scope"] = {k: v for k, v in dup.items() if v > 1}
        # 3) 範囲外の質問で順位 3 以内（県基準の率に数えられた可能性）
        out_scope = [r for r in rows if not (r["q_scope"] == "prefecture" and r["q_target"] == pref) and r["min_candidate_rank"] is not None and r["min_candidate_rank"] <= CUTOFF]
        info["rank_le3_outside_this_prefecture_scope"] = dict(Counter(f'{r["q_scope"]}/{r["q_target"]}' for r in out_scope))
        # 4) 率の行の Mart の件数と、導出の件数
        for rr in [x for x in rate_rows if x["municipality_id"] == mid]:
            cat = rr.get("category_id") or None
            d = {r["question_id"] for r in in_scope if r["min_candidate_rank"] is not None and r["min_candidate_rank"] <= CUTOFF and (cat is None or r["q_category"] == cat)}
            info[f'derived_{rr["metric_type"]}_{cat}'] = {"mart": rr["appearance_count"], "derived": len(d)}
        # 5) 順位 3 以内に数えうる候補（順位 NULL・4 以上で、状態・出所が特殊なもの）を CSV に
        for r in in_scope:
            r["in_derived_rank_le3"] = int(r["min_candidate_rank"] is not None and r["min_candidate_rank"] <= CUTOFF)
            qm_rows.append(r)
        s[mid] = info
    write_csv(out / "01_rate_rows.csv", rate_rows)
    write_csv(out / "02_qm_rows_in_scope.csv", qm_rows)
    # 6) 他の表に同じ自治体・質問の記録があるか（資源の出現など）
    extra = {}
    for t in ("appearance_asset_occurrence",):
        try:
            for mid, pref in TARGETS:
                extra[f"{t}:{mid}"] = a.execute(f"select count(*) from {t} where municipality_id=?", (mid,)).fetchone()[0]
        except Exception as e:
            extra[t] = str(e)
    s["extra"] = extra
    # 7) 同じ形のずれが他にもないか（県基準の全行で、率の分子と導出の差の分布。P1 の結果と同じはず）
    (out / "00_summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("出力:", out)
    print(json.dumps(s, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
