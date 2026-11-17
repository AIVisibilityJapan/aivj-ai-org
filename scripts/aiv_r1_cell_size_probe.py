#!/usr/bin/env python3
"""R1 用の確認（読み取り専用）: クロス・条件別の「セルの質問数」と、Mart 内の AI/モデル関連の列を数える。

目的
  (1) 3階層（全国/地方ブロック/都道府県）×条件の各セルが、何問で構成されるかを数え、
      標本30件未満（「—」扱い）のセルがどれだけ出るかを把握する。
  (2) Mart 内に AI・モデルを区別する列があるか、測定条件の記録がどこにあるかを一覧にする。

守ること
  - Mart は読み取り専用（mode=ro & immutable=1）で開く。書き込み・移動・削除・保存し直しはしない。
  - 出力は新しいフォルダにだけ書く（既存フォルダには触らない）。外部送信・API 実行なし。
  - 値は数えるだけ。補完・推測はしない。

使い方（リポジトリ直下）:
  py scripts\\aiv_r1_cell_size_probe.py
  py scripts\\aiv_r1_cell_size_probe.py --appearance "<出現率 Mart の sqlite>" --apa "<APA Mart の sqlite>"
  （--apa は省略可。省略時は出現率 Mart だけを調べる）

入力（既定）: 正式ルート AIV_FORMAL_ROOT_20261114\\AI Visibility 配下の
  01_正式成果物\\01_出現率\\Report Mart v2.4\\正式データ\\01_appearance_rate_report_mart_v2_4_final_release.sqlite
  01_正式成果物\\02_APA\\Report Mart\\正式データ\\01_MART\\apa_v1_report_mart.sqlite
出力: データ/private/06-STEP4作業/資源確認/出力/R1セル数確認_<日時>_<PID>/
"""
from __future__ import annotations
import argparse, csv, itertools, json, os, re, sqlite3, statistics, sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path.cwd().resolve()
FORMAL = REPO / "データ/private/05-測定データ/AIV_FORMAL_ROOT_20261114/AI Visibility/01_正式成果物"
AP_DEFAULT = FORMAL / "01_出現率/Report Mart v2.4/正式データ/01_appearance_rate_report_mart_v2_4_final_release.sqlite"
APA_DEFAULT = FORMAL / "02_APA/Report Mart/正式データ/01_MART/apa_v1_report_mart.sqlite"
OUT_BASE = REPO / "データ/private/06-STEP4作業/資源確認/出力"
MIN_N = 30  # 標本30件未満は「—」（全冊共通の表記ルール）
DIMS = ["category_id", "traveler_type", "season", "itinerary"]
DIM_JA = {"category_id": "旅行目的", "traveler_type": "同行者", "season": "季節", "itinerary": "旅程"}
AI_PATTERN = re.compile(r"(provider|model|engine|llm|vendor|chatgpt|gemini|claude|openai|ai_name|ai_id|reasoning)", re.I)


def ro(p: Path) -> sqlite3.Connection:
    c = sqlite3.connect(p.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    c.row_factory = sqlite3.Row
    return c


def tables(con):
    return [r[0] for r in con.execute("select name from sqlite_master where type in ('table','view') order by name")]


def cols(con, t):
    return [r[1] for r in con.execute(f'pragma table_info("{t}")')]


def scan_ai_columns(con, label):
    """AI・モデルを示しうる列名と、測定条件の記録がありそうな表を一覧にする（値は読まない・件数のみ）。"""
    rows = []
    for t in tables(con):
        cs = cols(con, t)
        hit = [c for c in cs if AI_PATTERN.search(c)]
        rows.append({"mart": label, "table": t, "column_count": len(cs), "ai_like_columns": "／".join(hit)})
    return rows


def distinct_values(con, t, c, limit=30):
    try:
        return [r[0] for r in con.execute(f'select distinct "{c}" from "{t}" limit {limit}')]
    except sqlite3.Error as e:  # noqa: BLE001
        return [f"(error: {e})"]


def stats(vals):
    if not vals:
        return {"cells": 0}
    return {"cells": len(vals), "min": min(vals), "median": statistics.median(vals), "max": max(vals),
            "below_30": sum(v < MIN_N for v in vals), "ge_30": sum(v >= MIN_N for v in vals)}


def cell_sizes(con):
    """appearance_question から、(scope種別, scope_target) ごと・条件の組み合わせごとの質問数を数える。"""
    q = [dict(r) for r in con.execute(
        "select question_id, category_id, scope, scope_target_id, traveler_type, season, itinerary from appearance_question")]
    norm = lambda v: "(空)" if v is None or v == "" else str(v)
    for r in q:
        for d in DIMS:
            r[d] = norm(r[d])
    out_rows, summary = [], []
    scopes = sorted({r["scope"] for r in q})
    patterns = [(d,) for d in DIMS] + list(itertools.combinations(DIMS, 2))
    for sc in scopes:
        qs = [r for r in q if r["scope"] == sc]
        targets = sorted({r["scope_target_id"] for r in qs})
        summary.append({"pattern": "(スコープ全体の質問数)", "scope": sc, **stats(
            [sum(1 for r in qs if r["scope_target_id"] == t) for t in targets]), "scope_targets": len(targets)})
        for pat in patterns:
            cnt = Counter()
            for r in qs:
                cnt[(r["scope_target_id"],) + tuple(r[d] for d in pat)] += 1
            # 値の取りうる全組合せ（質問に1問も無いセルは 0 として数える）
            levels = [sorted({r[d] for r in qs}) for d in pat]
            vals = []
            for t in targets:
                for combo in itertools.product(*levels):
                    n = cnt.get((t,) + combo, 0)
                    vals.append(n)
                    out_rows.append({"scope": sc, "scope_target_id": t,
                                     "pattern": "×".join(DIM_JA[d] for d in pat),
                                     "cell": "／".join(combo), "question_count": n, "below_30": n < MIN_N})
            summary.append({"pattern": "×".join(DIM_JA[d] for d in pat), "scope": sc, **stats(vals), "scope_targets": len(targets)})
    return out_rows, summary


def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    keys = list(rows[0])
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--appearance", default=str(AP_DEFAULT))
    ap.add_argument("--apa", default=str(APA_DEFAULT))
    ap.add_argument("--no-apa", action="store_true")
    a = ap.parse_args()
    ap_path, apa_path = Path(a.appearance), Path(a.apa)
    if not ap_path.exists():
        sys.exit(f"出現率 Mart が見つかりません: {ap_path}")
    out = OUT_BASE / f"R1セル数確認_{datetime.now():%Y%m%d_%H%M%S}_{os.getpid()}"
    out.mkdir(parents=True, exist_ok=False)  # 既存フォルダには触らない（衝突時は停止）
    report = {"appearance_mart": str(ap_path), "min_n": MIN_N, "note": "読み取り専用。値は数えるだけ。"}

    a_con = ro(ap_path)
    ai_rows = scan_ai_columns(a_con, "appearance")
    # 測定条件の記録（1行表）をそのまま写す
    for t in ("appearance_measurement", "appearance_build_metadata"):
        if t in tables(a_con):
            report[t] = [dict(r) for r in a_con.execute(f'select * from "{t}"')]
    report["appearance_scope_kinds"] = distinct_values(a_con, "appearance_scope", "scope")
    report["appearance_question_distinct"] = {c: distinct_values(a_con, "appearance_question", c)
                                              for c in ("scope", "traveler_type", "season", "itinerary", "category_id")}
    rows, summary = cell_sizes(a_con)
    write_csv(out / "01_cell_sizes_all.csv", rows)
    write_csv(out / "02_cell_size_summary.csv", summary)
    # 各質問に対する回答 AI の列が質問・出現の表にあるか
    report["question_tables_columns"] = {t: cols(a_con, t) for t in
                                         ("appearance_question", "appearance_question_municipality", "appearance_rate", "appearance_dimension_rate")
                                         if t in tables(a_con)}
    a_con.close()

    if not a.no_apa and apa_path.exists():
        p_con = ro(apa_path)
        ai_rows += scan_ai_columns(p_con, "apa")
        for t in ("formal_source_registry", "comparison_source_registry"):
            if t in tables(p_con):
                report[f"apa_{t}_columns"] = cols(p_con, t)
        p_con.close()
    elif not a.no_apa:
        report["apa_note"] = f"APA Mart が見つからないため確認していません: {apa_path}"

    write_csv(out / "03_ai_like_columns.csv", ai_rows)
    (out / "00_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # 画面には要点だけを出す
    print("出力:", out)
    print(f"--- セルの質問数（標本 {MIN_N} 件未満＝「—」）---")
    for s in summary:
        if s.get("cells"):
            print(f"{s['scope']:<14}{s['pattern']:<16} セル数={s['cells']:<5} 最小={s['min']} 中央={s['median']} 最大={s['max']} 30未満={s['below_30']} 30以上={s['ge_30']}")
    hits = [r for r in ai_rows if r["ai_like_columns"]]
    print(f"--- AI・モデルを示しうる列名のある表: {len(hits)} 件（詳細は 03_ai_like_columns.csv。値の中身は未確認）---")
    for r in hits[:20]:
        print(f"{r['mart']}.{r['table']}: {r['ai_like_columns']}")


if __name__ == "__main__":
    main()
