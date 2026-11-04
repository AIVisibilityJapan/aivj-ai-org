"""レポート制作 AI（AI-03-05）の道具: FMT v2.22 のひな形に、整理済みの値を差し込む。外部通信なし。

- 入力: ひな形 PPTX（読み取り専用）・AI-03-01 が整理した値・案件パラメータ（発行日・次回配信・測定期間）。
- 出力: 新しい PPTX（別名）。ひな形・値・原本は書き換えない。
- 差し込み項目 {{…}} は、対応表（TOKENS）にあるものだけ。対応のない項目・値が空の項目が 1 つでもあれば、出力せず止める（fail closed）。
- 値は作らない（計算・推測・補完をしない）。正式データの文字をそのまま入れる。
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

TOKEN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


class FillStop(Exception):
    pass


def build_token_map(org: dict, params: dict) -> dict:
    f = org["report_fields"]
    m = org["municipality"]
    res = {r["no"]: r.get("display") for r in org["resources"]}  # 無い資源は正式データ自身の表示『―』
    region = f["SCORE_TH_2"]
    t = {
        "municipality.name": m["municipality"],
        "municipality.prefecture_name": m["prefecture"],
        "municipality.region_block_name": region[:-len("ブロック")] if region.endswith("ブロック") else region,
        "report.id": m["report_id"],
        "report.issue_date": params["issue_date"],
        "report.next_issue_date": params["next_issue_date"],
        "appearance.national.rate_display": f["SCORE_RATE_1"],
        "appearance.region_block.rate_display": f["SCORE_RATE_2"],
        "appearance.prefecture.rate_display": f["SCORE_RATE_3"],
        "report.apa.overall.national.grade": f["SCORE_GRADE_1"],
        "report.apa.overall.region_block.grade": f["SCORE_GRADE_2"],
        "report.apa.overall.prefecture.grade": f["SCORE_GRADE_3"],
        "report.apa.overall.national.grade_range": f["SCORE_SUB_1"],
        "report.apa.overall.region_block.grade_range": f["SCORE_SUB_2"],
        "report.apa.overall.prefecture.grade_range": f["SCORE_SUB_3"],
        "report.appearance.high_categories.display": f["HIGH_VALUE"],
        "report.appearance.low_categories.display": f["LOW_VALUE"],
        "apa.negative.detected_display": f["NEG_STATUS"],
        "apa.negative.count_display": f["NEG_COUNT"],
        "report.apa.top_genre_1.name": f["COMP_R2C1"],
        "report.apa.top_genre_2.name": f["COMP_R3C1"],
    }
    for n in (1, 2, 3):
        t[f"report.apa.overall.competitor_{n}.display"] = f[f"COMP_R1C{n + 1}"]
        t[f"report.apa.top_genre_1.competitor_{n}.display"] = f[f"COMP_R2C{n + 1}"]
        t[f"report.apa.top_genre_2.competitor_{n}.display"] = f[f"COMP_R3C{n + 1}"]
        t[f"appearance.asset.top_{n}.display"] = res.get(n)
    return t


def _set_paragraph_text(par, text: str):
    runs = par.runs
    runs[0].text = text
    for r in runs[1:]:
        r._r.getparent().remove(r._r)


def _fill_frame(tf, tokens: dict, used: set):
    for par in tf.paragraphs:
        txt = "".join(r.text for r in par.runs)
        if "{{" not in txt and "}}" not in txt:
            continue

        def sub(mo):
            k = mo.group(1)
            if k not in tokens:
                raise FillStop(f"対応表にない差し込み項目: {{{{{k}}}}}")
            v = tokens[k]
            if v is None or v == "":
                raise FillStop(f"値が空の差し込み項目: {{{{{k}}}}}（0 や『―』で埋めない）")
            used.add(k)
            return v

        new = TOKEN.sub(sub, txt)
        if "{{" in new or "}}" in new:
            raise FillStop(f"差し込み項目を解釈できない: {txt}")
        lines = new.split("\n")
        _set_paragraph_text(par, lines[0])
        prev = par
        for extra in lines[1:]:  # 値の中の改行は段落を増やして表す
            clone = copy.deepcopy(par._p)
            prev._p.addnext(clone)
            from pptx.text.text import _Paragraph
            prev = _Paragraph(clone, par._parent)
            _set_paragraph_text(prev, extra)


def fill(template_path, org: dict, params: dict, out_path, overrides: dict | None = None) -> dict:
    """overrides: {図形名: 文字}。ひな形に差し込み項目がなく固定文が入っている項目（測定期間など）を案件ごとに置き換える。"""
    from pptx import Presentation

    for k in ("issue_date", "next_issue_date"):
        if not params.get(k):
            raise FillStop(f"案件パラメータが未指定: {k}")
    out_path = Path(out_path)
    if out_path.resolve() == Path(template_path).resolve():
        raise FillStop("ひな形を上書きしない")
    tokens = build_token_map(org, params)
    prs = Presentation(str(template_path))
    used: set = set()
    seen_override = set()
    for slide in prs.slides:
        for sh in slide.shapes:
            if not sh.has_text_frame:
                continue
            if overrides and sh.name in overrides:
                _set_paragraph_text(sh.text_frame.paragraphs[0], overrides[sh.name]); seen_override.add(sh.name)
                continue
            _fill_frame(sh.text_frame, tokens, used)
    if overrides and set(overrides) - seen_override:
        raise FillStop(f"置き換え先の図形が見つからない: {sorted(set(overrides) - seen_override)}")
    prs.save(str(out_path))
    return {"out": str(out_path), "tokens_used": len(used)}
