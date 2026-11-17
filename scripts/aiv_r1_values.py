#!/usr/bin/env python3
"""R1（地域ビジビリティ・詳細版）T1: 値取り出し。正式データから 1 自治体分の「値ファイル」を作る（読み取り専用）。

設計: 文書/設計/R1_T1_値取り出し_実装設計.md（決定: D-054, D-057〜D-062）。
作るもの: values.json（スロットごとの値・状態・出所）、slot_status.csv、evidence/（原文）、manifest.json。
作らないもの: 文章・分類・レポート組立（T4・T6・T8 の仕事）。

守ること
  - 正式データ（Mart・pointer・contract・Gate）は読み取り専用（mode=ro&immutable=1）。書き込み・移動・削除なし。
  - 版と SHA-256 を固定して参照し、不一致なら停止する（fail closed）。最新を自動探索しない。
  - 実測値・推計値・不明を区別し、欠損を 0% にしない。VALUE 以外の値は null。
  - 外部送信・API 実行・再測定をしない。出力は新しいフォルダにだけ書く。

使い方（リポジトリ直下 C:\\dev\\aivj-ai-org で）:
  py scripts\\aiv_r1_values.py --ids 304018
  py scripts\\aiv_r1_values.py --ids MUNI_304018 MUNI_322032 --out データ\\private\\06-STEP4作業\\R1\\値ファイル
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ------------------------------------------------------------------ 固定値（社長決定・設計書）
PERIOD = "2026年9月1日～9月30日"  # D-062（出現率・APA とも測定日）
AI_MEASURED = ["ChatGPT"]
AI_ALL = ["ChatGPT", "Gemini", "Claude"]
MIN_N = 30  # 標本が 30 未満の値は出さない（INSUFFICIENT_SAMPLE）
NEAR_N = 3  # 近接の件数（D-058）
TOKYO23 = "APA_TOKYO_23"
BLOCK_NA = {None, "", "__NOT_APPLICABLE__"}
EXPECT = {"appearance_municipality": 1747, "reporting_target": 1741, "questions": 14592, "apa_master": 1719, "rankings": 27504}
# 再現ゲートの既知の例外（D-060）。Mart は別の都道府県の質問の順位 3 以内の記録を自県基準の分子に数えている。Mart の値を使う
KNOWN_EXCEPTIONS = {
    ("MUNI_194298", "prefecture", "overall_scope_rate", ""), ("MUNI_194298", "prefecture", "category_scope_rate", "PUR_08"),
    ("MUNI_412015", "prefecture", "overall_scope_rate", ""), ("MUNI_412015", "prefecture", "category_scope_rate", "PUR_08"),
}
EXCEPTION_IDS = {k[0] for k in KNOWN_EXCEPTIONS}
# モデル名（社長決定 D-063）。values.json の meta にだけ記録し、レポート本文には載せない（D-061）
MODELS = {
    "appearance": {"ChatGPT": {"model": "gpt-4.1-mini", "status": "VALUE", "source": "社長回答 2026-11-17（D-063）",
                               "note": "本番 14,592 件の全件を示す production manifest は未確認（Codex に所在を確認中）"}},
    "apa": {"ChatGPT": {"model": "gpt-5.4-mini", "status": "VALUE", "source": "社長回答 2026-11-17（D-063）",
                        "note": "Codex の記録は gpt-5.4-mini-2026-03-17、Responses API、reasoning.effort=none。11,175 比較で model・model_version が全件一致の監査記録あり"}},
}
EVAL_IDS = ["overall", "hot_spring", "nature", "history_culture", "gourmet", "urban_tourism", "solo_travel", "couple_travel",
            "family_travel", "friends_travel", "day_trip", "overnight", "spring", "summer", "autumn", "winter"]
TIERS = ["national", "region_block", "prefecture"]
DIMS = ["category", "traveler", "season", "itinerary"]
DIM_COL = {"category": "category_id", "traveler": "traveler_type", "season": "season", "itinerary": "itinerary"}
# 順位帯（aiv_make_free_report.py の TH・NAT と同じ）
TH = [(0.067, "A++", "上位0.1％以上6.7％未満"), (0.134, "A+", "上位6.7％以上13.4％未満"), (0.20, "A", "上位13.4％以上20％未満"),
      (0.40, "B", "上位20％以上40％未満"), (0.60, "C", "上位40％以上60％未満"), (0.80, "D", "上位60％以上80％未満"), (1.0, "E", "上位80％以上100％")]
NAT = [(33, "A++", "1〜33位"), (67, "A+", "34〜67位"), (100, "A", "68〜100位"), (200, "B", "101〜200位"),
       (300, "C", "201〜300位"), (500, "D", "301〜500位"), (10 ** 9, "E", "501〜1,719位")]


class StopError(Exception):
    """fail closed: 値ファイルを作らずに止まる理由。"""


# ------------------------------------------------------------------ 基本部品
def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def stat_key(p: Path) -> tuple:
    s = Path(p).stat()
    return (s.st_size, s.st_mtime_ns)


def open_ro(p: Path) -> sqlite3.Connection:
    c = sqlite3.connect(Path(p).resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    c.row_factory = sqlite3.Row
    return c


def has_table(con, t) -> bool:
    return con.execute("select 1 from sqlite_master where name=? and type in ('table','view')", (t,)).fetchone() is not None


def slot(status: str, value=None, **kw) -> dict:
    d = {"status": status, "value": value if status in ("VALUE", "EXPLICIT_ZERO") else None}
    if status == "EXPLICIT_ZERO":
        d["value"] = 0.0 if value is None else value
    d.update({k: v for k, v in kw.items() if v is not None})
    return d


def band(rank: int, pop: int) -> dict:
    lo = 1
    for t, g, txt in TH:
        hi = pop if t == 1.0 else math.ceil(round(pop * t, 6)) - 1
        if rank <= hi:
            return {"grade": g, "range_text": txt, "lo": lo, "hi": hi, "population": pop}
        lo = hi + 1
    raise StopError(f"順位帯を決められません: rank={rank} pop={pop}")


def nat_band(rank: int) -> dict:
    for hi, g, txt in NAT:
        if rank <= hi:
            return {"grade": g, "range_text": txt}
    raise StopError(f"順位帯を決められません: rank={rank}")


def is_tokyo_ward(mid: str) -> bool:
    return mid.startswith("MUNI_131") and len(mid) == 11


def norm_id(x: str) -> str:
    x = x.strip()
    return x if x.startswith("MUNI_") else f"MUNI_{x}"


# ------------------------------------------------------------------ pin の解決（aiv_make_free_report.resolve_formal と同じ手順）
def resolve_pins(formal_root: Path) -> dict:
    root = Path(formal_root)
    lj = lambda p: json.loads(Path(p).read_text(encoding="utf-8-sig"))
    g = root / "03_実行基盤・コード" / "03_診断レポート" / "現行レポート基盤" / "03_generated" / "config"
    pointer_p = g / "resource_coverage_preflight_formal_current.json"
    if not pointer_p.exists():
        raise StopError(f"現行 pointer が見つかりません: {pointer_p}")
    gp = lj(pointer_p)
    contract_p = root / gp["source_contract_path"]
    if sha256_file(contract_p) != gp["source_contract_sha256"]:
        raise StopError("source contract の SHA が pointer の記載と一致しません")
    con = lj(contract_p)
    rows = {r["logical_source_name"]: r for r in con["sources"]}
    pins = {"pointer": {"path": str(pointer_p), "sha256": sha256_file(pointer_p), "gate_version": gp.get("gate_version")},
            "source_contract": {"path": str(contract_p), "sha256": gp["source_contract_sha256"], "version": gp.get("source_contract_version")}}
    for name in ("appearance_mart", "apa_report_mart"):
        if name not in rows:
            raise StopError(f"contract に {name} がありません（あるもの: {sorted(rows)}）")
    for name in ("appearance_mart", "apa_report_mart", "gate_municipality_status"):
        r = rows.get(name)
        if r is None:
            pins[name] = None
            continue
        p = root / r["path_relative_to_formal_root"]
        if not p.exists():
            raise StopError(f"{name} のファイルがありません: {p}")
        pins[name] = {"path": str(p), "sha256_expected": r["sha256"], "row": {k: v for k, v in r.items() if k != "sha256"}}
    return pins


def verify_pin_sha(pins: dict, names=("appearance_mart", "apa_report_mart", "gate_municipality_status")) -> None:
    for n in names:
        p = pins.get(n)
        if p is None:
            continue
        got = sha256_file(Path(p["path"]))
        if got != p["sha256_expected"]:
            raise StopError(f"{n} の SHA が contract の記載と一致しません: {got[:12]}… ≠ {p['sha256_expected'][:12]}…")
        p["sha256"] = got
        p["stat_before"] = list(stat_key(Path(p["path"])))


# ------------------------------------------------------------------ 検証ゲート
class Gates:
    def __init__(self):
        self.items = []

    def check(self, name: str, ok: bool, detail="", fatal: bool = True):
        self.items.append({"name": name, "ok": bool(ok), "detail": detail, "fatal": fatal})
        if not ok and fatal:
            raise StopError(f"検証ゲート失敗: {name} {detail}")


def count_gate(app, apa, gates: Gates, expect: dict | None):
    if expect is None:
        gates.check("件数ゲート", True, "省略（expect=None）", fatal=False)
        return
    got = {"appearance_municipality": app.execute("select count(*) from appearance_municipality").fetchone()[0],
           "reporting_target": app.execute("select count(*) from appearance_municipality where reporting_target_flag in (1,'1','true','TRUE','True')").fetchone()[0],
           "questions": app.execute("select count(*) from appearance_question").fetchone()[0],
           "apa_master": apa.execute("select count(*) from municipality_master").fetchone()[0],
           "rankings": apa.execute("select count(*) from rankings").fetchone()[0]}
    for k, v in expect.items():
        gates.check(f"件数: {k}", got[k] == v, f"実測 {got[k]} / 期待 {v}")


def rank_gate(apa, gates: Gates):
    for ev, n, mn, mx, d in apa.execute("select evaluation_id, count(*), min(rank), max(rank), count(distinct rank) from rankings group by evaluation_id"):
        gates.check(f"順位: {ev}", mn == 1 and mx == n and d == n, f"件数 {n} 最小 {mn} 最大 {mx} 異なる順位 {d}")


def reproduction_gate(app, cutoff: int, gates: Gates) -> dict:
    """質問単位の表から Mart の率（overall／category の scope 別）と次元別の率（全体基準）を再導出して照合する。"""
    q = {}
    for r in app.execute("select question_id, scope, scope_target_id, category_id, traveler_type, season, itinerary from appearance_question"):
        q[r["question_id"]] = (r["scope"], r["scope_target_id"], r["category_id"], r["traveler_type"], r["season"], r["itinerary"])
    qm = defaultdict(set)
    for r in app.execute("select question_id, municipality_id, min_candidate_rank from appearance_question_municipality"):
        if r["min_candidate_rank"] is not None and r["min_candidate_rank"] <= cutoff:
            qm[r["municipality_id"]].add(r["question_id"])
    denom = defaultdict(int)
    for sc, tg, cat, *_ in q.values():
        denom[(sc, tg, cat)] += 1
        denom[(sc, tg, None)] += 1
        denom[("all_scopes", "__ALL_SCOPES__", cat)] += 1
        denom[("all_scopes", "__ALL_SCOPES__", None)] += 1
    n = skipped = exc = 0
    bad = []
    for r in app.execute("select municipality_id, scope, scope_target_id, category_id, metric_type, appearance_count, valid_response_count from appearance_rate "
                         "where metric_type in ('overall_scope_rate','category_scope_rate','overall_all_scopes_rate','category_all_scopes_rate')"):
        mid, sc, tg, cat = r["municipality_id"], r["scope"], r["scope_target_id"], (r["category_id"] or None)
        if tg == "__NOT_APPLICABLE__" or r["appearance_count"] is None:
            skipped += 1
            continue
        n += 1
        mine = sum(1 for qid in qm.get(mid, ()) if (sc == "all_scopes" or (q[qid][0] == sc and q[qid][1] == tg)) and (cat is None or q[qid][2] == cat))
        d_ok = denom.get((sc, tg, cat), 0) == r["valid_response_count"]
        if mine == r["appearance_count"] and d_ok:
            continue
        key = (mid, sc, r["metric_type"], cat or "")
        if key in KNOWN_EXCEPTIONS and d_ok:
            exc += 1
        else:
            bad.append({"municipality_id": mid, "scope": sc, "target": tg, "category": cat, "metric": r["metric_type"],
                        "mart": r["appearance_count"], "derived": mine, "denominator_ok": d_ok})
    dim_n = dim_bad = 0
    if has_table(app, "appearance_dimension_rate"):
        idx = {"traveler": 3, "season": 4, "itinerary": 5}
        for r in app.execute("select municipality_id, dimension_type, dimension_value, appearance_count, valid_response_count from appearance_dimension_rate"):
            i = idx.get(r["dimension_type"])
            if i is None:
                continue
            dim_n += 1
            mine = sum(1 for qid in qm.get(r["municipality_id"], ()) if q[qid][i] == r["dimension_value"])
            tot = sum(1 for v in q.values() if v[i] == r["dimension_value"])
            if mine != r["appearance_count"] or tot != r["valid_response_count"]:
                dim_bad += 1
    gates.check("再現ゲート: 率", not bad, f"比較 {n} 行・既知の例外 {exc} 行・対象外 {skipped} 行・不一致 {len(bad)} 行 {bad[:3]}")
    gates.check("再現ゲート: 次元別（全体基準）", dim_bad == 0, f"比較 {dim_n} 行・不一致 {dim_bad} 行")
    return {"rate_rows": n, "known_exceptions": exc, "not_applicable_rows": skipped, "dimension_rows": dim_n}


# ------------------------------------------------------------------ 導出
class Ctx:
    """1 回の実行で使い回す表（Mart から読むだけ）。"""

    def __init__(self, app, apa, cutoff: int):
        self.app, self.apa, self.cutoff = app, apa, cutoff
        self.muni = {r["municipality_id"]: dict(r) for r in app.execute("select * from appearance_municipality")}
        self.cat_name = {r["category_id"]: r["category_name"] for r in app.execute("select category_id, category_name from appearance_category order by category_id")}
        self.q = {r["question_id"]: dict(r) for r in app.execute("select question_id, scope, scope_target_id, category_id, traveler_type, season, itinerary from appearance_question")}
        self.apa_master = {r["municipality_id"]: dict(r) for r in apa.execute("select * from municipality_master")}
        self.rank = defaultdict(dict)
        for r in apa.execute("select municipality_id, evaluation_id, rank from rankings"):
            self.rank[r["evaluation_id"]][r["municipality_id"]] = int(r["rank"])
        # 所属: APA の自治体 → 出現率側のブロック（ID で結合）。県は APA 側の名称（無償レポートと同じ）
        ward_block = next((m["region_block_id"] for k, m in self.muni.items() if is_tokyo_ward(k)), None)
        self.block_of = {}
        for aid in self.apa_master:
            if aid == TOKYO23:
                self.block_of[aid] = ward_block
            else:
                m = self.muni.get(aid)
                self.block_of[aid] = m["region_block_id"] if m else None
        self.block_name = {m["region_block_id"]: m["region_block_name"] for m in self.muni.values() if m["region_block_id"] not in BLOCK_NA}
        self.pref_of = {aid: m["prefecture"] for aid, m in self.apa_master.items()}


def tier_targets(rows: dict) -> dict:
    """この自治体の各階層の対象 ID（Mart の率の行から読む。形式を仮定しない）。"""
    out = {}
    for t in TIERS:
        r = rows.get(("overall_scope_rate", t, None))
        out[t] = r["scope_target_id"] if r else None
    return out


def rate_slot(row, label: str = "") -> dict:
    if row is None:
        return slot("NO_FORMAL_ROW", note="Mart に該当の行がない")
    if row["scope_target_id"] == "__NOT_APPLICABLE__" or row["appearance_count"] is None:
        return slot("NOT_APPLICABLE", note="対象外（地域ブロックなど）")
    n, c = row["valid_response_count"], row["appearance_count"]
    src = f"appearance_rate#rate_id={row['rate_id']}"
    if n is None:
        return slot("NOT_AVAILABLE", source=src)
    if n < MIN_N:
        return slot("INSUFFICIENT_SAMPLE", n=n, count=c, source=src, note=f"標本が {MIN_N} 未満")
    vs = row["value_status"]
    if vs == "EXPLICIT_ZERO":
        return slot("EXPLICIT_ZERO", 0.0, n=n, count=c, source=src, kind=row["formal_or_derived"])
    if vs == "VALUE":
        return slot("VALUE", row["appearance_rate"], n=n, count=c, source=src, kind=row["formal_or_derived"])
    return slot("NOT_AVAILABLE", n=n, source=src, note=f"value_status={vs}")


def derived_slot(count: int, n: int, source: str, note: str | None = None) -> dict:
    if n == 0:
        return slot("NO_FORMAL_ROW", note="該当する質問がない", source=source)
    if n < MIN_N:
        return slot("INSUFFICIENT_SAMPLE", n=n, count=count, source=source, note=note or f"標本が {MIN_N} 未満")
    if count == 0:
        return slot("EXPLICIT_ZERO", 0.0, n=n, count=count, source=source, note=note)
    return slot("VALUE", count / n, n=n, count=count, source=source, note=note)


def competition_ranks(vals: dict) -> dict:
    ordered = sorted(vals.values(), reverse=True)
    out = {}
    for k, v in vals.items():
        out[k] = 1 + sum(1 for x in ordered if x > v)
    return out


def derive(ctx: Ctx, mid: str) -> dict:
    app, apa = ctx.app, ctx.apa
    m = ctx.muni.get(mid)
    if m is None:
        raise StopError(f"出現率 Mart に自治体がありません: {mid}")
    apa_id = TOKYO23 if is_tokyo_ward(mid) else mid
    if apa_id not in ctx.apa_master:
        raise StopError(f"APA に自治体がありません: {apa_id}")
    slots, ev = {}, {}
    notes = []

    # --- Mart の率の行
    rows = {}
    for r in app.execute("select * from appearance_rate where municipality_id=?", (mid,)):
        rows[(r["metric_type"], r["scope"], r["category_id"] or None)] = dict(r)
    tg = tier_targets(rows)
    tier_of_scope = {"national": "national", "region_block": "region_block", "prefecture": "prefecture"}
    exc_note = "既知の例外（D-060）: Mart は別の都道府県の質問を自県基準の分子に数えている。Mart の値と 1 件ずれる可能性" if mid in EXCEPTION_IDS else None

    # G01 測定条件
    slots["G01.period"] = slot("VALUE", PERIOD)
    slots["G01.ai_measured"] = slot("VALUE", AI_MEASURED)
    bm = app.execute("select * from appearance_build_metadata").fetchone()
    slots["G01.population.appearance"] = slot("VALUE", int(bm["reporting_target_count"])) if bm else slot("NOT_AVAILABLE")
    slots["G01.population.apa"] = slot("VALUE", len(ctx.apa_master))
    slots["G01.questions.valid_response_count"] = slot("VALUE", int(bm["valid_response_count"])) if bm else slot("NOT_AVAILABLE")
    for t in TIERS:
        n = sum(1 for x in ctx.q.values() if x["scope"] == t and x["scope_target_id"] == tg[t]) if tg[t] not in BLOCK_NA else 0
        slots[f"G01.questions.{t}"] = slot("VALUE", n) if n else slot("NOT_APPLICABLE")

    # G03 総合（3 階層＋全体）
    for t in TIERS:
        slots[f"G03.overall.{t}"] = rate_slot(rows.get(("overall_scope_rate", t, None)))
    slots["G03.overall.all_scopes"] = rate_slot(rows.get(("overall_all_scopes_rate", "all_scopes", None)))
    # 旅行目的 8 × 3 階層（＋全体）
    for cid, cname in ctx.cat_name.items():
        for t in TIERS:
            slots[f"G03.category.{cid}.{t}"] = rate_slot(rows.get(("category_scope_rate", t, cid)))
            slots[f"G03.category.{cid}.{t}"]["label"] = cname
        slots[f"G03.category.{cid}.all_scopes"] = rate_slot(rows.get(("category_all_scopes_rate", "all_scopes", cid)))
        slots[f"G03.category.{cid}.all_scopes"]["label"] = cname
    # 強み・弱み（無償レポートと同じ規則: 全体基準のカテゴリ別率、同率は category_id 順）
    order = list(ctx.cat_name)
    rv = {c: rows.get(("category_all_scopes_rate", "all_scopes", c)) for c in order}
    if all(r is not None and r["appearance_rate"] is not None for r in rv.values()):
        vals = {c: rv[c]["appearance_rate"] for c in order}
        if len(set(vals.values())) == 1:
            slots["G03.high_categories"] = slot("VALUE", "ALL_EQUAL")
            slots["G03.low_categories"] = slot("VALUE", "ALL_EQUAL")
        else:
            hs = sorted(order, key=lambda c: (-vals[c], order.index(c)))[:2]
            ls = sorted([c for c in order if c not in hs], key=lambda c: (vals[c], order.index(c)))[:2]
            slots["G03.high_categories"] = slot("VALUE", hs)
            slots["G03.low_categories"] = slot("VALUE", ls)
    else:
        slots["G03.high_categories"] = slot("NO_FORMAL_ROW")
        slots["G03.low_categories"] = slot("NO_FORMAL_ROW")

    # 同行者・季節・旅程（全体基準は Mart、3 階層は質問単位から導出）と クロス
    mine_q = {r["question_id"] for r in app.execute("select question_id, min_candidate_rank from appearance_question_municipality where municipality_id=?", (mid,))
              if r["min_candidate_rank"] is not None and r["min_candidate_rank"] <= ctx.cutoff}
    # 上の select は min_candidate_rank を行ごとに見るため、再度条件つきで取り直す
    mine_q = {r["question_id"] for r in app.execute(
        "select question_id from appearance_question_municipality where municipality_id=? and min_candidate_rank is not null and min_candidate_rank<=?", (mid, ctx.cutoff))}

    def count_for(tier_scope, target, dimvals: dict):
        """tier_scope: 'national'|'region_block'|'prefecture'|'all_scopes'。dimvals: {dim: value}"""
        n = c = 0
        for qid, x in ctx.q.items():
            if tier_scope != "all_scopes" and (x["scope"] != tier_scope or x["scope_target_id"] != target):
                continue
            if any(x[DIM_COL[d]] != v for d, v in dimvals.items()):
                continue
            n += 1
            if qid in mine_q:
                c += 1
        return c, n

    values_by_dim = {d: sorted({x[DIM_COL[d]] for x in ctx.q.values() if x[DIM_COL[d]] not in (None, "")}) for d in DIMS}
    # Mart の次元別（全体基準）
    mdim = {}
    if has_table(app, "appearance_dimension_rate"):
        for r in app.execute("select * from appearance_dimension_rate where municipality_id=?", (mid,)):
            mdim[(r["dimension_type"], r["dimension_value"])] = dict(r)
    for d in ("traveler", "season", "itinerary"):
        for v in values_by_dim[d]:
            r = mdim.get((d, v))
            if r is None:
                slots[f"G03.dim.{d}.{v}.all_scopes"] = slot("NO_FORMAL_ROW")
            else:
                n, c = r["valid_response_count"], r["appearance_count"]
                s = derived_slot(c, n, f"appearance_dimension_rate#{d}={v}")
                if s["status"] == "VALUE":
                    s["value"] = r["appearance_rate"]
                s["kind"] = r["formal_or_derived"]
                slots[f"G03.dim.{d}.{v}.all_scopes"] = s
            for t in TIERS:
                sid = f"G03.dim.{d}.{v}.{t}"
                if tg[t] in BLOCK_NA:
                    slots[sid] = slot("NOT_APPLICABLE", note="対象外（地域ブロックなど）")
                    continue
                c, n = count_for(t, tg[t], {d: v})
                slots[sid] = derived_slot(c, n, f"derived:appearance_question_municipality[{d}={v},{t}={tg[t]}]", exc_note if t == "prefecture" else None)
    # クロス（6 パターン: 4 次元から 2 つ）
    for i, d1 in enumerate(DIMS):
        for d2 in DIMS[i + 1:]:
            for v1 in values_by_dim[d1]:
                for v2 in values_by_dim[d2]:
                    for t in TIERS + ["all_scopes"]:
                        sid = f"G06.cross.{d1}x{d2}.{v1}|{v2}.{t}"
                        if t != "all_scopes" and tg[t] in BLOCK_NA:
                            slots[sid] = slot("NOT_APPLICABLE", note="対象外（地域ブロックなど）")
                            continue
                        c, n = count_for(t, tg.get(t), {d1: v1, d2: v2})
                        slots[sid] = derived_slot(c, n, f"derived:cross[{d1}={v1},{d2}={v2},{t}]", exc_note if t == "prefecture" else None)

    # G03n 出現率の順位と近接（社長決定 D-059）: 率の降順・同率は同順位、近接は「厳密に高い率のうち最も近い 3 件」、足りなければ低い直近
    apa_overall = ctx.rank.get("overall", {})
    tie_key = lambda x: (apa_overall.get(TOKYO23 if is_tokyo_ward(x) else x, 10 ** 9), x)
    for t in TIERS:
        target = tg[t]
        if target in BLOCK_NA or target is None:
            slots[f"G03.rank.{t}"] = slot("NOT_APPLICABLE")
            continue
        pop = {}
        for r in app.execute("select municipality_id, appearance_rate, value_status from appearance_rate where metric_type='overall_scope_rate' and scope=? and scope_target_id=?", (t, target)):
            mm = ctx.muni.get(r["municipality_id"])
            if mm and str(mm["reporting_target_flag"]) in ("1", "True", "true", "TRUE") and r["value_status"] in ("VALUE", "EXPLICIT_ZERO") and r["appearance_rate"] is not None:
                pop[r["municipality_id"]] = round(float(r["appearance_rate"]), 12)
        if mid not in pop:
            slots[f"G03.rank.{t}"] = slot("NO_FORMAL_ROW", note="順位づけの母集団に自治体がない")
            continue
        rk = competition_ranks(pop)
        slots[f"G03.rank.{t}"] = slot("VALUE", rk[mid], population=len(pop), source=f"appearance_rate[{t}={target}]")
        r0 = pop[mid]
        higher = sorted((k for k, v in pop.items() if v > r0), key=lambda k: (pop[k], tie_key(k)))[:NEAR_N]
        pick = [(k, "higher") for k in higher]
        if len(pick) < NEAR_N:
            lower = sorted((k for k, v in pop.items() if v < r0), key=lambda k: (-pop[k], tie_key(k)))[:NEAR_N - len(pick)]
            pick += [(k, "lower") for k in lower]
        pick.sort(key=lambda kv: (-pop[kv[0]], tie_key(kv[0])))
        for j, (k, side) in enumerate(pick, start=1):
            slots[f"G03.near.{t}.{j}"] = slot("VALUE", {"municipality_id": k, "name": ctx.muni[k]["municipality_name"], "rate": pop[k], "rank": rk[k], "side": side},
                                              population=len(pop))
        for j in range(len(pick) + 1, NEAR_N + 1):
            slots[f"G03.near.{t}.{j}"] = slot("NO_FORMAL_ROW", note="近接の自治体が足りない")

    # G04 AI 別（ChatGPT のみ測定。他は未測定）
    for t in TIERS:
        for ai in AI_ALL:
            sid = f"G04.appearance.overall.{t}.{ai}"
            slots[sid] = dict(slots[f"G03.overall.{t}"]) if ai in AI_MEASURED else slot("NOT_MEASURED", unlock=f"{ai} の出現率測定")

    # G05 推移・前回比（過去期なし）
    for t in TIERS:
        slots[f"G05.change.appearance.overall.{t}"] = slot("NOT_MEASURED", unlock="過去期の測定")
    slots["G05.change.apa.overall.national"] = slot("NOT_MEASURED", unlock="過去期の測定")

    # G07 観光資源（Mart の値のまま。実在確認・帰属は T5。未確認の印を付ける）
    asset_rows = [dict(r) for r in app.execute("select * from municipality_asset_top5 where municipality_id=? order by metric_scope, asset_rank", (mid,))] \
        if has_table(app, "municipality_asset_top5") else []
    if not asset_rows:
        slots["G07.top5"] = slot("NO_FORMAL_ROW", note="資源の出現記録がない（または上位に入る資源がない）")
    for r in asset_rows:
        base = f"G07.top5.{r['metric_scope']}.{r['asset_rank']}"
        denom = r.get("municipality_appearance_question_count")
        st = "INSUFFICIENT_SAMPLE" if (denom is not None and denom < MIN_N) else "VALUE"
        for key, col in (("name", "canonical_asset_name"), ("count", "question_count"), ("share", "share")):
            slots[f"{base}.{key}"] = slot(st, r[col], n=denom, asset_id=r["asset_id"], verification="UNCHECKED（T5 の実在確認ゲート前）",
                                          note=("言及回数 = 質問数（P3）" if key == "count" else None))
    ev["asset_top5"] = asset_rows
    ev["asset_occurrence"] = [dict(r) for r in app.execute(
        "select municipality_id, metric_scope, asset_id, question_id, candidate_rank, category_id, scope, scope_target_id, candidate_text, canonical_asset_name from appearance_asset_occurrence where municipality_id=?",
        (mid,))] if has_table(app, "appearance_asset_occurrence") else []

    # G08 APA 自治体ランク（16 項目 × 3 階層）
    pref = ctx.pref_of[apa_id]
    blk = ctx.block_of.get(apa_id)
    nbr_evidence = []
    for e in EVAL_IDS:
        rk = ctx.rank.get(e, {})
        if apa_id not in rk:
            for t in TIERS:
                slots[f"G08.rank.{e}.{t}"] = slot("NO_FORMAL_ROW", note="APA の順位がない")
            continue
        nat = rk[apa_id]
        slots[f"G08.rank.{e}.national"] = slot("VALUE", nat, population=len(rk), band=nat_band(nat), source=f"rankings[{e}]")
        if blk in BLOCK_NA:
            slots[f"G08.rank.{e}.region_block"] = slot("NOT_APPLICABLE", note="地域ブロックの対象外（北海道・沖縄）")
            blk_order = None
        else:
            blk_order = sorted((a for a in rk if ctx.block_of.get(a) == blk), key=lambda a: rk[a])
            pos = blk_order.index(apa_id) + 1
            slots[f"G08.rank.{e}.region_block"] = slot("VALUE", pos, population=len(blk_order), band=band(pos, len(blk_order)), source=f"rankings[{e}]+block={blk}")
        pref_order = sorted((a for a in rk if ctx.pref_of.get(a) == pref), key=lambda a: rk[a])
        posp = pref_order.index(apa_id) + 1
        slots[f"G08.rank.{e}.prefecture"] = slot("VALUE", posp, population=len(pref_order), band=band(posp, len(pref_order)), source=f"rankings[{e}]+pref={pref}")
        for ai in AI_ALL:
            if ai not in AI_MEASURED:
                slots[f"G04.apa.{e}.national.{ai}"] = slot("NOT_MEASURED", unlock=f"{ai} の APA 測定")
        slots[f"G04.apa.{e}.national.ChatGPT"] = dict(slots[f"G08.rank.{e}.national"])
        # G09 競合（近接の採り方: 順位が高い直近 3、足りなければ低い直近。D-057/D-058）
        for t, order_ in (("national", sorted(rk, key=lambda a: rk[a])), ("region_block", blk_order), ("prefecture", pref_order)):
            if order_ is None:
                for j in range(1, NEAR_N + 1):
                    slots[f"G09.{e}.{t}.near{j}"] = slot("NOT_APPLICABLE", note="地域ブロックの対象外")
                continue
            i = order_.index(apa_id)
            above = [order_[i - k] for k in range(1, NEAR_N + 1) if i - k >= 0]
            pick = [(a, "higher") for a in above]
            if len(pick) < NEAR_N:
                pick += [(order_[i + k], "lower") for k in range(1, NEAR_N - len(pick) + 1) if i + k < len(order_)]
            pick.sort(key=lambda x: order_.index(x[0]))
            for j, (a, side) in enumerate(pick, start=1):
                info = {"municipality_id": a, "name": ctx.apa_master[a]["municipality_name"], "prefecture": ctx.apa_master[a]["prefecture"],
                        "national_rank": rk[a], "tier_rank": order_.index(a) + 1, "side": side}
                slots[f"G09.{e}.{t}.near{j}"] = slot("VALUE", info, population=len(order_))
                recs = [dict(r) for r in apa.execute(
                    "select municipality_id, evaluation_id, comparison_id, stage, round, opponent_id, opponent_name, result, recommended_reason, not_recommended_reason, "
                    "self_positive_reason, self_negative_reason, opponent_positive_reason, opponent_negative_reason from municipality_comparisons "
                    "where municipality_id=? and evaluation_id=? and opponent_id=? order by stage, round, comparison_id", (apa_id, e, a))]
                slots[f"G09.{e}.{t}.near{j}.reason"] = (slot("VALUE", {"records": len(recs)}, source="municipality_comparisons") if recs
                                                         else slot("NO_FORMAL_ROW", note="直接の対戦記録がない（理由欄は「—」）"))
                for r in recs:
                    r.update({"tier": t, "near_slot": j})
                    nbr_evidence.append(r)
            for j in range(len(pick) + 1, NEAR_N + 1):
                slots[f"G09.{e}.{t}.near{j}"] = slot("NO_FORMAL_ROW", note="近接の自治体が足りない")
    ev["competitor_reasons"] = nbr_evidence

    # G10 ネガティブ（件数は理由文単位。分類は T4）
    ns = apa.execute("select * from municipality_negative_summary where municipality_id=?", (apa_id,)).fetchone()
    if ns is None:
        slots["G10.negative.total"] = slot("NO_FORMAL_ROW")
    else:
        slots["G10.negative.total"] = slot("VALUE", int(ns["negative_reason_count_total_raw"]), unit="理由文", source="municipality_negative_summary")
        slots["G10.negative.unique_exact"] = slot("VALUE", int(ns["negative_reason_unique_exact_total"]), unit="理由文（完全一致を除く）", source="municipality_negative_summary")
        slots["G10.negative.evaluations_with_negative"] = slot("VALUE", int(ns["evaluations_with_negative"]), source="municipality_negative_summary")
    for r in apa.execute("select * from negative_summary where municipality_id=?", (apa_id,)):
        slots[f"G10.negative.{r['evaluation_id']}.count"] = slot("VALUE", int(r["negative_reason_count_raw"]), unit="理由文", source="negative_summary")
    ev["negative_reasons"] = [dict(r) for r in apa.execute(
        "select municipality_id, evaluation_id, comparison_id, opponent_id, opponent_name, stage, round, negative_reason, normalized_negative_reason "
        "from negative_reasons where municipality_id=? order by evaluation_id, comparison_id", (apa_id,))]

    # G11 観光スポット APA（未測定・保留）
    slots["G11.spot_apa"] = slot("NOT_MEASURED", unlock="観光スポット単位の APA 測定（保留）")
    # G12・G13 は T1 では値を作らない
    slots["G12.summary"] = slot("NOT_AVAILABLE", note="他のデータ群に従属。T1 では作らない")
    slots["G13.proposals"] = slot("NOT_AVAILABLE", note="T8 の仕事。T1 では作らない")

    meta = {"municipality_id": mid, "apa_id": apa_id, "name": m["municipality_name"], "prefecture": m["prefecture_name"],
            "region_block_id": m["region_block_id"], "region_block_name": m["region_block_name"], "tier_targets": tg,
            "report_kind": "R1", "measurement_period": PERIOD, "ai_measured": AI_MEASURED, "models": MODELS,
            "known_exception_municipality": mid in EXCEPTION_IDS}
    return {"meta": meta, "slots": slots, "evidence": ev, "notes": notes}


# ------------------------------------------------------------------ 出力
def write_csv(path: Path, rows: list[dict]):
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def write_outputs(out_dir: Path, result: dict, pins: dict, gates: Gates, args_dict: dict, gate_info: dict | None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=False)  # 既存フォルダには書かない
    meta = dict(result["meta"])
    meta["pins"] = {k: ({kk: vv for kk, vv in v.items() if kk != "stat_before"} if isinstance(v, dict) else v) for k, v in pins.items()}
    meta["gate_municipality_status"] = gate_info
    (out_dir / "values.json").write_text(json.dumps({"meta": meta, "slots": result["slots"]}, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    rows = [{"slot_id": k, "status": v["status"], "unlock": v.get("unlock", ""), "note": v.get("note", "")} for k, v in sorted(result["slots"].items())]
    write_csv(out_dir / "slot_status.csv", rows)
    (out_dir / "evidence").mkdir()
    for k, v in result["evidence"].items():
        write_csv(out_dir / "evidence" / f"{k}.csv", v) if v else (out_dir / "evidence" / f"{k}.csv").write_text("", encoding="utf-8-sig")
    files = {str(p.relative_to(out_dir)): sha256_file(p) for p in sorted(out_dir.rglob("*")) if p.is_file()}
    manifest = {"created_at": datetime.now().isoformat(timespec="seconds"), "args": args_dict, "gates": gates.items, "outputs_sha256": files,
                "inputs": {k: {"path": v["path"], "sha256": v.get("sha256"), "stat_before": v.get("stat_before")} for k, v in pins.items() if isinstance(v, dict) and "path" in v},
                "status_counts": {s: sum(1 for x in result["slots"].values() if x["status"] == s) for s in sorted({x["status"] for x in result["slots"].values()})}}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_dir


def read_gate_row(gate_path: Path | None, mid: str):
    if not gate_path or not Path(gate_path).exists():
        return None
    with Path(gate_path).open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("municipality_id") == mid:
                return dict(r)
    return {"municipality_id": mid, "status": "NOT_FOUND_IN_GATE"}


def run(app_path: Path, apa_path: Path, ids: list[str], out_base: Path, pins: dict, expect: dict | None = EXPECT,
        gate_path: Path | None = None, args_dict: dict | None = None) -> list[Path]:
    """pin 済みの 2 つの Mart から値ファイルを作る。pins は verify_pin_sha 済み（試験では手で作る）。"""
    app, apa = open_ro(app_path), open_ro(apa_path)
    gates = Gates()
    try:
        count_gate(app, apa, gates, expect)
        rank_gate(apa, gates)
        meas = app.execute("select formal_rank_cutoff from appearance_measurement").fetchone()
        cutoff = int(meas["formal_rank_cutoff"]) if meas else 3
        gates.check("順位の閾値", cutoff == 3, f"formal_rank_cutoff={cutoff}（設計は 3）")
        repro = reproduction_gate(app, cutoff, gates)
        ctx = Ctx(app, apa, cutoff)
        outs = []
        stamp = f"{datetime.now():%Y%m%d_%H%M%S}_{os.getpid()}"
        for mid in ids:
            res = derive(ctx, mid)
            # 値の範囲ゲート
            for sid, s in res["slots"].items():
                if s["status"] in ("VALUE", "EXPLICIT_ZERO") and isinstance(s["value"], float) and sid.startswith(("G03.overall", "G03.category", "G03.dim", "G06")):
                    gates.check(f"値の範囲: {sid}", 0.0 <= s["value"] <= 1.0, f"value={s['value']}")
                if s["status"] not in ("VALUE", "EXPLICIT_ZERO") and s["value"] is not None:
                    gates.check(f"VALUE 以外に値がある: {sid}", False)
            res["meta"]["reproduction_gate"] = repro
            gi = read_gate_row(gate_path, mid)
            out = write_outputs(out_base / f"{mid}_{stamp}", res, pins, gates, args_dict or {}, gi)
            outs.append(out)
    finally:
        app.close()
        apa.close()
    # 入力が変わっていないこと
    for n in ("appearance_mart", "apa_report_mart", "gate_municipality_status"):
        p = pins.get(n)
        if p and p.get("stat_before") and list(stat_key(Path(p["path"]))) != p["stat_before"]:
            raise StopError(f"実行中に入力が変わりました: {n}")
    return outs


def main():
    ap = argparse.ArgumentParser(description="R1 T1 値取り出し（読み取り専用）")
    ap.add_argument("--formal-root", default="データ/private/05-測定データ/AIV_FORMAL_ROOT_20261114/AI Visibility")
    ap.add_argument("--ids", nargs="+", required=True, help="自治体 ID（MUNI_304018）または 6 桁の団体コード（304018）")
    ap.add_argument("--out", default="データ/private/06-STEP4作業/R1/値ファイル")
    ap.add_argument("--ignore-gate", action="store_true", help="Gate 判定表に自治体がなくても止めない（試作用。警告だけ記録する）")
    a = ap.parse_args()
    try:
        pins = resolve_pins(Path(a.formal_root).resolve())
        verify_pin_sha(pins)
        ids = [norm_id(x) for x in a.ids]
        gp = pins.get("gate_municipality_status")
        outs = run(Path(pins["appearance_mart"]["path"]), Path(pins["apa_report_mart"]["path"]), ids, Path(a.out).resolve(), pins,
                   gate_path=Path(gp["path"]) if gp else None, args_dict={"ids": ids, "ignore_gate": a.ignore_gate})
    except StopError as e:
        print(f"■ 止まりました（値ファイルは作っていません）: {e}", file=sys.stderr)
        sys.exit(2)
    for o in outs:
        print("出力:", o)


if __name__ == "__main__":
    main()
