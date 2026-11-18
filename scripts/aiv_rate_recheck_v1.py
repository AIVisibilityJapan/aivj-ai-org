#!/usr/bin/env python3
"""出現率の再計算の試験。完全読み取り専用（何も書き込まない）。採用の判断には使わない（試験のみ）。
Report Mart（出現率 v2.4）の「候補の解決表」（回答から取り出した名前の一覧）から、出現数を数え直し、保存済みの値と比べる。
  段階 1（--schema）: 表・列の構造を表示。
  段階 2（既定）: ①方法の検証: 保存済みの出現数と、数え直した値を 4 自治体で比べる（長岡京市・福岡市・八幡市・和泉市）。
              ②長岡京市の取りこぼし探し: 名前に長岡京市の資源らしい語を含む候補が、ほかの自治体に解決されていないか。
注意: 「回答原文」そのもの（API 応答 JSON）は引継ぎで未回収。ここで見るのは、回答から取り出された名前（candidate_name）まで。
実行（リポジトリ直下）: py scripts\\aiv_rate_recheck_v1.py
"""
from __future__ import annotations
import sqlite3, sys
from pathlib import Path

R = Path(__file__).resolve().parents[1]
AP = R / "データ/private/05-測定データ/AIV_NEW_PC_HANDOFF_20261105/01_AI_Visibility/01_正式成果物/01_出現率/Report Mart v2.4/正式データ/01_appearance_rate_report_mart_v2_4_final_release.sqlite"
TARGETS = [("長岡京市", "MUNI_262099"), ("福岡市", "MUNI_401307"), ("八幡市", "MUNI_262102"), ("和泉市", "MUNI_272191")]
KEYS = ["長岡京", "長岡天満", "天満宮", "光明寺", "乙訓寺", "恵解山", "長岡宮", "勝竜寺", "勝龍寺", "向日", "西山", "錦水亭", "八条", "バンブー", "竹の径", "乙訓"]

def q(c, sql, a=()):
    return c.execute(sql, a).fetchall()

def main():
    if not AP.is_file():
        raise SystemExit(f"STOP: Mart が無い: {AP}")
    c = sqlite3.connect(AP.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    print("=== ① 方法の検証（保存済みの出現数 と 数え直した値）===")
    print("定義: 出現 = 上位 3 位以内（candidate_rank<=3）の候補が、その自治体に解決された質問（質問 ID の重複を除く）")
    for name, mid in TARGETS:
        stored = q(c, "select appearance_count, valid_response_count, appearance_rate, value_status from appearance_rate where municipality_id=? and metric_type='overall_all_scopes_rate'", (mid,))
        a = q(c, "select count(distinct question_id) from appearance_candidate_resolution where resolved_municipality_id=? and candidate_rank<=3", (mid,))[0][0]
        b = q(c, "select count(distinct question_id) from appearance_question_municipality where municipality_id=? and min_candidate_rank<=3", (mid,))[0][0]
        c3 = q(c, "select count(distinct question_id) from appearance_candidate_resolution where resolved_municipality_id=? and rank_class='RANK1_3'", (mid,))[0][0]
        print(f"{name}({mid}): 保存済み={stored} / 候補表から数え直し(rank<=3)={a} / RANK1_3 区分で={c3} / 質問×自治体表(min_rank<=3)={b}")
    print("\n=== ② 長岡京市の取りこぼし探し（名前に語を含む候補。解決先ごと）===")
    for k in KEYS:
        rows = q(c, "select ifnull(resolved_municipality_id,'(なし)'), final_resolution_status, rank_class, count(*), count(distinct question_id), group_concat(distinct candidate_name) from appearance_candidate_resolution where candidate_name like ? group by 1,2,3 order by 4 desc limit 8", (f"%{k}%",))
        print(f"\n[{k}] {len(rows)} 区分")
        for r in rows:
            print("  ", r[0], r[1], r[2], f"行={r[3]} 質問={r[4]}", "名前例=", str(r[5])[:90])
    print("\n=== ③ 長岡京市に関わる行の総数（解決先・元・文脈のどれかが長岡京市）===")
    for col in ("resolved_municipality_id", "original_municipality_id", "context_municipality_id"):
        print(col, q(c, f"select rank_class, count(*), count(distinct question_id) from appearance_candidate_resolution where {col}='MUNI_262099' group by 1"))
    print("\n=== ④ 長岡京市のまとめ（Mart の不足理由表）===")
    print(q(c, "select appearance_count, active_asset_count, missing_top3_slots, dictionary_gap_count, human_review_count, municipality_self_count, cross_count, primary_missing_reason, detail from appearance_asset_missing_reason where municipality_id='MUNI_262099'"))

if __name__ == "__main__":
    main()
