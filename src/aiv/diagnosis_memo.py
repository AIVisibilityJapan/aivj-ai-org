"""AIO 診断 AI（AI-04-01）の道具（STEP 4 試験版）: 整理済みの値から、診断メモ（読み取れる事実の要約）を作る。外部通信なし。

- 値は書き換えず、各記述に根拠の項目名（source）を付ける。数値・順位を新しく作らない。
- 改善提案は作らない（無償レポートに改善提案の章がない。公式サイトの取得・解析は外部接続になるため本試験では行わない）。
"""
from __future__ import annotations


def make_memo(org: dict) -> dict:
    m, mt, f = org["municipality"], org["metrics"], org["report_fields"]
    rate, rank = mt["appearance_rate"], mt["apa_rank"]
    facts = []

    def add(text, source):
        facts.append({"text": text, "source": source})

    add(f"出現率（{rate['unit']}）: 全国 {rate['scopes']['national']['display']}／"
        f"{f['SCORE_TH_2']} {rate['scopes']['region']['display']}／{f['SCORE_TH_3']} {rate['scopes']['prefecture']['display']}",
        ["SCORE_RATE_1", "SCORE_RATE_2", "SCORE_RATE_3"])
    n, rg, pf = rank["national"], rank["region"], rank["prefecture"]
    add(f"自治体ランキング（{rank['unit']}）: 全国 {n['rank']}位（評価 {n['grade']}）／{rg['name']} {rg['rank']}位・全{rg['population']}自治体（{rg['grade']}）"
        f"／{pf['name']} {pf['rank']}位・全{pf['population']}自治体（{pf['grade']}）",
        ["SCORE_GRADE_1", "SCORE_GRADE_2", "SCORE_GRADE_3", "SCORE_SUB_1", "SCORE_SUB_2", "SCORE_SUB_3"])
    add(f"評価の高い分野: {f['HIGH_VALUE']}／評価の低い分野: {f['LOW_VALUE']}", ["HIGH_VALUE", "LOW_VALUE"])
    comp = [f[f"COMP_R1C{i}"] for i in (2, 3, 4)]
    add("総合で順位が近い競合: " + "、".join(comp), ["COMP_R1C2", "COMP_R1C3", "COMP_R1C4"])
    names = [r["name"] for r in org["resources"] if r["name"]]
    add("出現を支える観光資源: " + ("、".join(names) if names else "（正式データに該当なし）"), ["ASSET_1", "ASSET_2", "ASSET_3"])
    ng = mt["negative"]
    add(f"ネガティブ情報: {ng['status']}（{ng['count']}件）", ["NEG_STATUS", "NEG_COUNT"])
    cautions = []
    zero = [k for k, v in rate["scopes"].items() if v["state"] == "UNVERIFIED_ZERO"]
    if zero:
        cautions.append(f"出現率 {', '.join(zero)} は 0.0%。Mart で『明示的な 0』か『行なし』かが未確認（0 と断定しない）")
    if not names:
        cautions.append("観光資源が正式データにない（空欄や推測で補わない）")
    return {"municipality": m["municipality"], "facts": facts, "cautions": cautions, "improvements": [],
            "note": "事実の要約のみ。改善提案は本試験では作らない（公式サイト等の外部取得を行わない）"}
