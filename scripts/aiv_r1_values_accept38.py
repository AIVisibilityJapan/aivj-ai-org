#!/usr/bin/env python3
"""R1 T1 の受入確認: 無償レポートで作成済みの 38 自治体の値（入力/report_values_s1550_38.json）と、T1 の値を突き合わせる。

読み取り専用。値ファイルは作らず、結果を CSV（受入確認_日時/）に書く。一致しない項目は「失敗」ではなく一覧で報告する
（参照の JSON は 2026-10-28 時点の値で、その後に正式データの版が進んでいる場合は差が出うる）。

使い方（リポジトリ直下）:
  py scripts\\aiv_r1_values_accept38.py
  py scripts\\aiv_r1_values_accept38.py --ids 304018 --reference <別の JSON>
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aiv_r1_values as T  # noqa: E402

EVAL_JA = {"hot_spring": "温泉", "gourmet": "グルメ", "nature": "自然景観", "history_culture": "歴史・文化",
           "urban_tourism": "都市観光", "spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬",
           "day_trip": "日帰り", "overnight": "宿泊", "solo_travel": "一人旅", "couple_travel": "カップル旅行",
           "family_travel": "家族旅行", "friends_travel": "友人旅行"}
CAT_DISPLAY = {"海・マリンレジャー": "海・川・湖のウォーターアクティビティ"}  # aiv_make_free_report.py と同じ表示名


def pct(v) -> str:
    return f"{v:.1%}"


def nb_text(info: dict) -> str:
    return f"{info['name']}（{info['prefecture']}）"


def cats(slots: dict, key: str) -> str:
    s = slots.get(key)
    if not s or s["status"] != "VALUE":
        return "—"
    if s["value"] == "ALL_EQUAL":
        return "全カテゴリ同率"
    out = []
    for cid in s["value"]:
        label = slots[f"G03.category.{cid}.all_scopes"].get("label", cid)
        out.append(CAT_DISPLAY.get(label, label))
    return "／".join(out)


def compare(ref: dict, values: dict) -> list[dict]:
    """参照 1 自治体（無償レポートの値）と T1 の values.json（dict）を項目ごとに比べる。"""
    s, f = values["slots"], ref["source_fields"]
    no_block = ref.get("region_rank") in (None, "―") or f.get("SCORE_RATE_2") == "―"
    rows = []

    def add(item, r, t):
        rows.append({"municipality_id": ref["municipality_id"], "municipality": ref["municipality"], "item": item,
                     "free_report": r, "t1": t, "match": "OK" if str(r) == str(t) else "DIFF"})

    def val(sid, key="value", default="—"):
        x = s.get(sid)
        return x[key] if x and x["status"] == "VALUE" and key in x else default

    add("APA総合 全国順位", ref["national_rank"], val("G08.rank.overall.national"))
    add("APA総合 全国 等級", ref["national_grade"], (s["G08.rank.overall.national"].get("band") or {}).get("grade", "—"))
    if not no_block:
        add("APA総合 ブロック順位", ref["region_rank"], val("G08.rank.overall.region_block"))
        add("APA総合 ブロック母数", ref["region_population"], val("G08.rank.overall.region_block", "population"))
        add("APA総合 ブロック 等級", ref["region_grade"], (s["G08.rank.overall.region_block"].get("band") or {}).get("grade", "—"))
    add("APA総合 県順位", ref["prefecture_rank"], val("G08.rank.overall.prefecture"))
    add("APA総合 県母数", ref["prefecture_population"], val("G08.rank.overall.prefecture", "population"))
    add("APA総合 県 等級", ref["prefecture_grade"], (s["G08.rank.overall.prefecture"].get("band") or {}).get("grade", "—"))
    for tier, rk, k in (("national", "national_rate", "SCORE_RATE_1"), ("region_block", "region_rate", "SCORE_RATE_2"), ("prefecture", "prefecture_rate", "SCORE_RATE_3")):
        if tier == "region_block" and no_block:
            continue
        x = s[f"G03.overall.{tier}"]
        add(f"出現率 {tier}", ref[rk], pct(x["value"]) if x["status"] in ("VALUE", "EXPLICIT_ZERO") else "—")
    add("評価の高い分野", f["HIGH_VALUE"], cats(s, "G03.high_categories"))
    add("評価の低い分野", f["LOW_VALUE"], cats(s, "G03.low_categories"))
    add("ネガティブ件数", ref["negative_count"], val("G10.negative.total"))
    # 競合（総合と、順位の高い 2 項目）。無償レポートの近接も「順位が直前の 3 件（上位 3 位以内は上位 4 件から自分を除く）」
    def near(e):
        out = []
        for j in (1, 2, 3):
            x = s.get(f"G09.{e}.national.near{j}")
            out.append(nb_text(x["value"]) if x and x["status"] == "VALUE" else "—")
        return out

    for j, t in enumerate(near("overall"), start=2):
        add(f"競合 総合 近接{j - 1}", f[f"COMP_R1C{j}"], t)
    ranks = sorted(((s[f"G08.rank.{e}.national"]["value"], e) for e in EVAL_JA if s.get(f"G08.rank.{e}.national", {}).get("status") == "VALUE"))
    for i, (_, e) in enumerate(ranks[:2], start=2):
        add(f"競合 分野{i - 1} 名称", f[f"COMP_R{i}C1"], EVAL_JA[e])
        for j, t in enumerate(near(e), start=2):
            add(f"競合 {EVAL_JA[e]} 近接{j - 1}", f[f"COMP_R{i}C{j}"], t)
    return rows


def main():
    ap = argparse.ArgumentParser(description="R1 T1 受入確認（無償レポート 38 自治体との突き合わせ）")
    ap.add_argument("--formal-root", default="データ/private/05-測定データ/AIV_FORMAL_ROOT_20261114/AI Visibility")
    ap.add_argument("--reference", default="データ/private/06-STEP4作業/入力/report_values_s1550_38.json")
    ap.add_argument("--ids", nargs="*", default=[], help="対象を絞る（省略すると参照の全件）")
    ap.add_argument("--out", default="データ/private/06-STEP4作業/R1/受入確認")
    a = ap.parse_args()
    try:
        refs = json.loads(Path(a.reference).read_text(encoding="utf-8-sig"))
        want = {T.norm_id(x) for x in a.ids}
        refs = [r for r in refs if not want or r["municipality_id"] in want]
        if not refs:
            raise T.StopError("対象の自治体がありません")
        pins = T.resolve_pins(Path(a.formal_root).resolve())
        T.verify_pin_sha(pins, ("appearance_mart", "apa_report_mart"))
        app, apa = T.open_ro(Path(pins["appearance_mart"]["path"])), T.open_ro(Path(pins["apa_report_mart"]["path"]))
        gates = T.Gates()
        T.count_gate(app, apa, gates, T.EXPECT)
        T.rank_gate(apa, gates)
        T.reproduction_gate(app, 3, gates)
        ctx = T.Ctx(app, apa, 3)
        rows = []
        for r in refs:
            res = T.derive(ctx, r["municipality_id"])
            rows += compare(r, {"slots": res["slots"]})
            print(f"{r['municipality']}: 比較済み", flush=True)
        app.close()
        apa.close()
    except T.StopError as e:
        print(f"■ 止まりました: {e}", file=sys.stderr)
        sys.exit(2)
    out = Path(a.out).resolve() / f"受入確認_{datetime.now():%Y%m%d_%H%M%S}"
    out.mkdir(parents=True)
    with (out / "比較結果.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    diffs = [r for r in rows if r["match"] != "OK"]
    with (out / "差のある項目.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(diffs)
    by = {}
    for r in diffs:
        by[r["item"].split(" ")[0]] = by.get(r["item"].split(" ")[0], 0) + 1
    print(f"自治体 {len(refs)} 件 / 比較 {len(rows)} 項目 / 一致 {len(rows) - len(diffs)} / 差 {len(diffs)}")
    print("差の内訳（項目の先頭語）:", by)
    print("出力:", out)


if __name__ == "__main__":
    main()
