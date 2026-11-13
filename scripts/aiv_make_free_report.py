#!/usr/bin/env python3
"""無償診断レポート（FMT v2.24）を、導出済みの入力から作る。読み取り専用の入力 → 新しいフォルダへ出力のみ。

使い方（リポジトリ直下）:
  py scripts\\aiv_make_free_report.py --ids MUNI_304018 MUNI_322032 --tag テスト
  py scripts\\aiv_make_free_report.py --verify38        # 完成済み38件を作り直して完成品と全文字を照合
  py scripts\\aiv_make_free_report.py --all-allowed --tag テスト   # Gate許可の全自治体を一括作成（要: 各取り出しスクリプトを --all で実行済み）

入力（06-STEP4作業 配下を --work で指定。省略時は既定）:
  FMT/無償レポート_FMTv2.24.pptx
  資源確認/出力/値探索_*/02_membership.csv, 01_category_rates.csv   （aiv_values_explore.py）
  資源確認/出力/COMP探索2_*/01_ranks_by_eval.csv                      （aiv_comp_rule_probe2.py）
  資源確認/出力/追加値_*/01_rates_overall.csv, 02_negative.csv        （aiv_values_extra_export.py）
  資源確認/入力/diagnostic_selector_v1_5_51_formal_slots_*.csv, gate_municipality_status_v1_1_8.csv
  入力/report_values_s1550_38.json（検証用）
各ディレクトリは最新の日時のものを使う。
"""
from __future__ import annotations
import argparse, copy, csv, glob, json, math, sys
from datetime import date
from pathlib import Path

import pandas as pd
from pptx import Presentation

TH = [(0.067, "A++", "上位0.1％以上6.7％未満"), (0.134, "A+", "上位6.7％以上13.4％未満"),
      (0.20, "A", "上位13.4％以上20％未満"), (0.40, "B", "上位20％以上40％未満"),
      (0.60, "C", "上位40％以上60％未満"), (0.80, "D", "上位60％以上80％未満"), (1.0, "E", "上位80％以上100％")]
NAT = [(33, "A++", "1〜33位"), (67, "A+", "34〜67位"), (100, "A", "68〜100位"), (200, "B", "101〜200位"),
       (300, "C", "201〜300位"), (500, "D", "301〜500位"), (10 ** 9, "E", "501〜1,719位")]
EVAL_JA = {"hot_spring": "温泉", "gourmet": "グルメ", "nature": "自然景観", "history_culture": "歴史・文化",
           "urban_tourism": "都市観光", "spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬",
           "day_trip": "日帰り", "overnight": "宿泊", "solo_travel": "一人旅", "couple_travel": "カップル旅行",
           "family_travel": "家族旅行", "friends_travel": "友人旅行"}
CAT_DISPLAY = {"海・マリンレジャー": "海・川・湖のウォーターアクティビティ"}
COND_DATE = "2026年9月1日～9月30日"
NEXT_DATE = "2027年1月"


TOKYO23 = "APA_TOKYO_23"


def is_tokyo_ward(mid: str) -> bool:
    return mid.startswith("MUNI_131") and len(mid) == 11


class HoldError(Exception):
    """作らずに保留にする（方針の決定が必要）理由。"""


def latest(base: Path, pattern: str) -> Path:
    c = sorted(glob.glob(str(base / pattern)))
    if not c:
        sys.exit(f"入力が見つかりません: {base / pattern}")
    return Path(c[-1])


def neighbors(row) -> list[str]:
    """比較相手の3自治体。通常は直前の3自治体（昇順）。順位が3位以内なら、自分を除いて上位から3件で補う（社長決定 2026-11-10）。"""
    r = int(row["rank"])
    if r >= 4:
        return [row.above1, row.above2, row.above3]
    if "top1" not in row.index:
        raise HoldError("取り出しデータに上位4位の名前がありません（aiv_comp_rule_probe2.py --all を再実行してください）")
    top = [row.top1, row.top2, row.top3, row.top4]
    return [x for i, x in enumerate(top, start=1) if i != r][:3]


def band(rank: int, pop: int, label: str):
    lo = 1
    for t, g, txt in TH:
        hi = pop if t == 1.0 else math.ceil(round(pop * t, 6)) - 1
        if rank <= hi:
            return g, f"{txt}\n（{label}内{lo}〜{hi}位相当／全{pop}自治体）"
        lo = hi + 1
    raise ValueError(rank)


def nat_band(rank: int):
    for hi, g, txt in NAT:
        if rank <= hi:
            return g, txt


class Data:
    def __init__(self, work: Path, slots_file: Path | None = None, gate_file: Path | None = None):
        res = work / "資源確認" / "出力"
        self.work = work
        m = pd.read_csv(latest(res, "値探索_*") / "02_membership.csv", encoding="utf-8-sig")
        m["blk"] = m.block_app
        m.loc[m.name_apa == "東京23区", "blk"] = "関東地方"
        self.m = m
        self.cat = pd.read_csv(latest(res, "値探索_*") / "01_category_rates.csv", encoding="utf-8-sig")
        self.order = list(self.cat.category_name.unique())
        self.ev = pd.read_csv(latest(res, "COMP探索2_*") / "01_ranks_by_eval.csv", encoding="utf-8-sig").fillna("")
        ex = latest(res, "追加値_*")
        self.rates = pd.read_csv(ex / "01_rates_overall.csv", encoding="utf-8-sig")
        self.neg = pd.read_csv(ex / "02_negative.csv", encoding="utf-8-sig")
        slots = slots_file or latest(work / "資源確認" / "入力", "diagnostic_selector_v1_5_51_formal_slots_*.csv")
        self.slots = pd.read_csv(slots, encoding="utf-8-sig", dtype=str).fillna("")
        self.gate = pd.read_csv(gate_file or work / "資源確認" / "入力" / "gate_municipality_status_v1_1_8.csv", encoding="utf-8-sig", dtype=str).fillna("")

    def values(self, mid: str, use_slots: bool = True) -> dict:
        m = self.m
        # 東京23区: 出現率は各区、APAは APA_TOKYO_23 の1単位（区ごとのAPA順位は存在しない・分割しない）
        apa_id = TOKYO23 if is_tokyo_ward(mid) else mid
        row = m[m.municipality_id == apa_id].iloc[0]
        name, pref, blk = row.name_apa, row.pref_apa, row.blk
        if apa_id != mid:
            g = self.gate[self.gate.municipality_id == mid].iloc[0]
            name = g.municipality_name  # 都道府県は APA_TOKYO_23 の「東京都」を使う（Gate表では空欄）
        rank = int(row.overall_rank)
        blk_s = m[m.blk == blk].sort_values("overall_rank")
        region_rank = list(blk_s.municipality_id).index(apa_id) + 1 if not pd.isna(blk) else None
        pf_s = m[m.pref_apa == pref].sort_values("overall_rank")
        pref_rank = list(pf_s.municipality_id).index(apa_id) + 1
        ng, nb = nat_band(rank)
        no_block = pd.isna(blk)
        if no_block:  # 北海道・沖縄県は地域ブロック（9区分）の対象外。表示だけ「―」にする
            rg, rb, region_rank = "―", "―", None
        else:
            rg, rb = band(region_rank, len(blk_s), blk.replace("地方", "ブロック"))
        pg, pb = band(pref_rank, len(pf_s), pref)
        ov = self.rates[(self.rates.municipality_id == mid) & (self.rates.metric_type == "overall_scope_rate")].set_index("scope").appearance_rate
        rate = [f"{ov[s]:.1%}" if (s != "region_block" or not no_block) else "―" for s in ("national", "region_block", "prefecture")]
        # 強み・弱み
        g = self.cat[(self.cat.municipality_id == mid) & (self.cat.scope == "all_scopes")].set_index("category_name").appearance_rate
        r = {c: g[c] for c in self.order}
        if len(set(r.values())) == 1:
            high = low = "全カテゴリ同率"
        else:
            hs = sorted(self.order, key=lambda c: (-r[c], self.order.index(c)))[:2]
            ls = sorted([c for c in self.order if c not in hs], key=lambda c: (r[c], self.order.index(c)))[:2]
            high = "／".join(CAT_DISPLAY.get(c, c) for c in hs)
            low = "／".join(CAT_DISPLAY.get(c, c) for c in ls)
        # 比較表
        e = self.ev[self.ev.municipality_id == apa_id]
        o = e[e.evaluation_id == "overall"].iloc[0]
        n = neighbors(o)
        comp = {"R1C1": "総合", "R1C2": n[0], "R1C3": n[1], "R1C4": n[2]}
        top = e[e.evaluation_id != "overall"].sort_values(["rank", "evaluation_id"]).head(2)
        warn = []
        for i, t in enumerate(top.itertuples(), start=2):
            n = neighbors(pd.Series(t._asdict()))
            comp.update({f"R{i}C1": EVAL_JA[t.evaluation_id], f"R{i}C2": n[0], f"R{i}C3": n[1], f"R{i}C4": n[2]})
        # 資源
        assets = ["―", "―", "―"]
        if use_slots:
            s = self.slots[self.slots.municipality_id == mid].sort_values("display_slot")
            for x in s.itertuples():
                assets[int(x.display_slot) - 1] = x.canonical_name or "―"
        n = int(self.neg[self.neg.municipality_id == apa_id].negative_reason_count_total_raw.iloc[0])
        return {"mid": mid, "name": name, "pref": pref, "block": ("地域ブロック（対象外）" if no_block else blk.replace("地方", "ブロック")), "no_block": bool(no_block), "code": mid.replace("MUNI_", ""),
                "rank": rank, "rate": rate, "grades": [ng, rg, pg], "subs": [nb, rb, pb], "high": high, "low": low,
                "comp": comp, "assets": assets, "neg": n, "warn": warn}


def set_text(shape, text: str):
    tf = shape.text_frame
    lines = text.split("\n")
    paras = list(tf.paragraphs)
    while len(paras) < len(lines):
        new = copy.deepcopy(paras[0]._p)
        paras[-1]._p.addnext(new)
        paras = list(tf.paragraphs)
    for extra in paras[len(lines):]:
        extra._p.getparent().remove(extra._p)
    paras = list(tf.paragraphs)
    for p, line in zip(paras, lines):
        runs = list(p.runs)
        if not runs:
            p.add_run().text = line
            continue
        runs[0].text = line
        for r in runs[1:]:
            r._r.getparent().remove(r._r)


def wrap_value_box(shape, text: str):
    """評価の高い／低い分野: 青背景（PILL）の右端までを上限として折り返す。長い場合は文字を小さくして2行に収める。"""
    from lxml import etree
    ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    body = shape._element.find(".//a:bodyPr", ns)
    body.set("wrap", "square")
    for ch in list(body):
        body.remove(ch)
    etree.SubElement(body, "{%s}normAutofit" % ns["a"])  # fontScaleなし（固定サイズで制御）
    width_pt = shape.width / 12700
    n = len(text)
    size = 9
    for sz in (9, 8.5, 8, 7.5, 7):
        size = sz
        per_line = max(1, int(width_pt / sz))
        if -(-n // per_line) <= 2:
            break
    for r in shape.text_frame.paragraphs[0].runs:
        r.font.size = int(size * 12700)


def shape_map(v: dict, issue: str) -> dict:
    t = {
        "REPORT_ID": f"Report ID：AIV-{v['code']}-2026Q4", "ISSUE_DATE": f"発行日：{issue}",
        "FOOTER_LEFT": f"AI 可視性分析レポート［ダイジェスト版］／ {v['pref']} {v['name']}",
        "COND_VALUE_TARGET": f"{v['pref']} {v['name']}", "COND_VALUE_DATE": COND_DATE,
        "SCORE_TH_2": v["block"], "SCORE_TH_3": v["pref"],
        "HIGH_VALUE": v["high"], "LOW_VALUE": v["low"],
        "NEG_STATUS": "検出あり" if v["neg"] > 0 else "検出なし", "NEG_COUNT": f"{v['neg']}件", "NEXT_DATE": NEXT_DATE,
    }
    if v.get("no_block"):
        t["SCORE_FOOTNOTE"] = "※出現率は各基準で母集団が異なります。自治体ランキングはAPA総合順位を使用します。" + f"{v['pref']}は地域ブロックの対象外です。"
    for i in range(3):
        t[f"SCORE_RATE_{i+1}"] = v["rate"][i]
        t[f"SCORE_GRADE_{i+1}"] = v["grades"][i]
        t[f"SCORE_SUB_{i+1}"] = v["subs"][i]
        t[f"ASSET_{i+1}"] = v["assets"][i]
    for k, val in v["comp"].items():
        t[f"COMP_{k}"] = val
    return t


def build(template: Path, v: dict, issue: str, out: Path):
    prs = Presentation(str(template))
    t = shape_map(v, issue)
    for s in prs.slides:
        for sh in s.shapes:
            if sh.has_text_frame and sh.name in t:
                set_text(sh, t[sh.name])
                if sh.name in ("HIGH_VALUE", "LOW_VALUE"):
                    wrap_value_box(sh, t[sh.name])
    left = [sh.text_frame.text for s in prs.slides for sh in s.shapes if sh.has_text_frame and "{{" in sh.text_frame.text]
    if left:
        raise RuntimeError(f"未置換の項目があります: {left}")
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))


def texts(path: Path) -> dict:
    p = Presentation(str(path))
    return {(i, sh.name): sh.text_frame.text for i, s in enumerate(p.slides, 1) for sh in s.shapes if sh.has_text_frame}


def resolve_formal(root: Path) -> dict:
    """正式ルートの現行 pointer から、資源スロット表とGate判定表を取り出す（SHA照合つき・自動探索なし）。"""
    import hashlib
    sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    lj = lambda p: json.loads(Path(p).read_text(encoding="utf-8-sig"))
    g = root / "03_実行基盤・コード" / "03_診断レポート" / "現行レポート基盤" / "03_generated" / "config"
    sp = lj(g / "diagnostic_resource_selector_formal_current.json")
    pin = lj(root / sp["pin_path"])
    assert sha(root / sp["pin_path"]) is not None and pin["selector_version"] == sp["formal_selector_version"], "selector pin"
    cfg_p = root / pin["selector_config_path"]; assert sha(cfg_p) == pin["selector_config_sha256"], "selector config SHA"
    cfg = lj(cfg_p); slots = root / cfg["formal_slot_path"]; assert sha(slots) == cfg["formal_slot_sha256"], "slots SHA"
    gp = lj(g / "resource_coverage_preflight_formal_current.json")
    contract_p = root / gp["source_contract_path"]; assert sha(contract_p) == gp["source_contract_sha256"], "contract SHA"
    con = lj(contract_p); row = [r for r in con["sources"] if r["logical_source_name"] == "gate_municipality_status"][0]
    gate = root / row["path_relative_to_formal_root"]; assert sha(gate) == row["sha256"], "gate status SHA"
    return {"slots": slots, "gate": gate, "selector": sp["formal_selector_version"], "gate_version": gp["gate_version"], "contract": gp["source_contract_version"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="データ/private/06-STEP4作業")
    ap.add_argument("--ids", nargs="*", default=[])
    ap.add_argument("--tag", default="テスト")
    ap.add_argument("--issue", default=None, help="発行日（例: 2026年11月10日）。省略時は今日")
    ap.add_argument("--verify38", action="store_true")
    ap.add_argument("--all-allowed", action="store_true", help="Gate許可の全自治体を作る。作れない自治体は理由を manifest.csv に残して続行")
    ap.add_argument("--limit", type=int, default=0, help="--all-allowed の作成数の上限（試験用）")
    ap.add_argument("--out", default=None)
    ap.add_argument("--formal-root", default=None, help="正式ルート（…\\AI Visibility）。指定すると、現行 pointer の資源スロット表とGate判定表を使う（SHA照合つき）")
    ap.add_argument("--slots-file", default=None, help="試作用: 資源3枠の元になるスロット表を指定（追記stageの確認用。正式版ではない）")
    ap.add_argument("--ignore-gate", action="store_true", help="試作用: Gateが通っていない自治体でも試作を作る（正式版ではない）")
    ap.add_argument("--assets", default=None, help="試作用: 資源3枠を「A,B,C」で上書きする（Gate未通過の自治体でも試作を作る。正式版ではない。空欄は―）")
    a = ap.parse_args()
    work = Path(a.work).resolve()
    tpl = work / "FMT" / "無償レポート_FMTv2.24.pptx"
    fr = resolve_formal(Path(a.formal_root).resolve()) if a.formal_root else None
    if fr:
        print(json.dumps({"formal": {k: str(v) for k, v in fr.items()}}, ensure_ascii=False))
    d = Data(work, Path(a.slots_file).resolve() if a.slots_file else (fr["slots"] if fr else None), fr["gate"] if fr else None)
    today = date.today()
    issue = a.issue or f"{today.year}年{today.month}月{today.day}日"
    stamp = f"{today:%Y%m%d}"
    out_root = Path(a.out).resolve() if a.out else work / "出力" / f"無償レポート_{a.tag}_{stamp}"
    if a.verify38:
        vals = json.loads((work / "入力" / "report_values_s1550_38.json").read_text(encoding="utf-8-sig"))
        bad, tot = 0, 0
        for x in vals:
            v = d.values(x["municipality_id"], use_slots=False)
            v["assets"] = [r["asset_name"] for r in x["resources"]]  # 資源は完成時点の選定結果（検証対象外）
            out = out_root / f"verify_{x['municipality']}.pptx"
            build(tpl, v, "2026年10月28日", out)
            ref = work / "完成品" / f"無償レポート_{x['prefecture']}{x['municipality']}20261028.pptx"
            a_, b_ = texts(out), texts(ref)
            diff = [(k, a_.get(k), b_.get(k)) for k in set(a_) | set(b_) if a_.get(k) != b_.get(k)]
            tot += 1
            if diff:
                bad += 1
                print("DIFF", x["municipality"], diff[:3])
        print(json.dumps({"verified": tot, "mismatch": bad}, ensure_ascii=False))
        return
    if a.all_allowed:
        ok_gate = d.gate[d.gate.report_generation_allowed.str.upper() == "TRUE"]
        rows = []
        for g in ok_gate.itertuples():
            if a.limit and sum(r["status"] == "CREATED" for r in rows) >= a.limit:
                break
            rec = {"municipality_id": g.municipality_id, "name": g.municipality_name, "prefecture": g.prefecture, "status": "", "reason": "", "file": ""}
            try:
                mrow = d.m[d.m.municipality_id == (TOKYO23 if is_tokyo_ward(g.municipality_id) else g.municipality_id)]
                if mrow.empty:
                    raise HoldError("APAに該当する自治体単位がありません")
                v = d.values(g.municipality_id)
                if v["warn"]:
                    rec.update(status="HOLD", reason="；".join(v["warn"]))
                else:
                    out = out_root / f"{v['pref']}{v['name']}_無償診断レポート_{a.tag}.pptx"
                    build(tpl, v, issue, out)
                    rec.update(status="CREATED", file=str(out))
            except HoldError as e:
                rec.update(status="HOLD", reason=str(e))
            except Exception as e:  # noqa: BLE001
                rec.update(status="ERROR", reason=f"{type(e).__name__}: {e}")
            rows.append(rec)
        out_root.mkdir(parents=True, exist_ok=True)
        with (out_root / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
        from collections import Counter
        print(json.dumps({"summary": dict(Counter(r["status"] for r in rows)), "out": str(out_root)}, ensure_ascii=False))
        return
    for mid in a.ids:
        gate = d.gate[d.gate.municipality_id == mid]
        allowed = (gate.report_generation_allowed.iloc[0].upper() == "TRUE") if len(gate) else False
        v = d.values(mid)
        if a.assets is not None:
            names = [x.strip() or "―" for x in a.assets.split(",")][:3]
            v["assets"] = names + ["―"] * (3 - len(names))
            out = out_root / f"{v['name']}_無償診断レポート_{a.tag}_資源仮置き.pptx"
            build(tpl, v, issue, out)
            print(json.dumps({"municipality": v["name"], "out": str(out), "TRIAL": "資源は仮置き（正式版ではない）", "warn": v["warn"], "values": {
                "rank": v["rank"], "rate": v["rate"], "grades": v["grades"], "high": v["high"], "low": v["low"],
                "comp": v["comp"], "assets": v["assets"], "neg": v["neg"]}}, ensure_ascii=False))
            continue
        if a.ignore_gate and not allowed:
            out = out_root / f"{v['name']}_無償診断レポート_{a.tag}_Gate未通過試作.pptx"
            build(tpl, v, issue, out)
            print(json.dumps({"municipality": v["name"], "out": str(out), "TRIAL": "Gate未通過の試作（正式版ではない）", "warn": v["warn"], "values": {
                "rank": v["rank"], "rate": v["rate"], "grades": v["grades"], "high": v["high"], "low": v["low"],
                "comp": v["comp"], "assets": v["assets"], "neg": v["neg"]}}, ensure_ascii=False))
            continue
        if not allowed:
            print(f"SKIP {v['name']}: Gate が通っていません（{gate.decision_reason.iloc[0] if len(gate) else '不明'}）")
            continue
        out = out_root / f"{v['name']}_無償診断レポート_{a.tag}.pptx"
        build(tpl, v, issue, out)
        print(json.dumps({"municipality": v["name"], "out": str(out), "warn": v["warn"], "values": {
            "rank": v["rank"], "rate": v["rate"], "grades": v["grades"], "high": v["high"], "low": v["low"],
            "comp": v["comp"], "assets": v["assets"], "neg": v["neg"]}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
