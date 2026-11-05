"""無償診断レポート（採用したひな形 FMT・2 枚）の品質・リスク監査の検査器（AI-06-06 の道具）。

読み取り専用・外部通信なし。入力は『成果物の文字（図形名→文字）』『根拠の値（report_values の 1 件）』『自社表記の正本』。
成果物は書き換えない。指摘（findings）と合否だけを返す。作成側の文脈は受け取らない（成果物と根拠だけ）。
重大度: 重大・中 が 1 件でもあれば『不合格』。軽 だけなら『合格（指摘あり）』。判断できなかった項目（not_judged）が残り、不合格でなければ『保留』。
重大度の基準（対外的な影響・D-049）: 重大＝事実・数値の誤り／禁止表現／社名・協会名の誤り／秘密の混入、中＝住所・電話・メールの誤記、軽＝区切りなどの表記の揺れ。
対象範囲: 文字と数値だけ。レイアウト・図・色は見ない（将来の拡張。それまでは社長が確認時に PowerPoint で目視する）。
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import yaml

PROFILE_PATH = Path(__file__).with_name("canonical_profile.yaml")
SEV_FAIL = {"重大", "中"}

NATIONAL_BANDS = [(33, "A++"), (67, "A+"), (100, "A"), (200, "B"), (300, "C"), (500, "D"), (1719, "E")]
PCT_BANDS = [(6.7, "A++"), (13.4, "A+"), (20.0, "A"), (40.0, "B"), (60.0, "C"), (80.0, "D"), (100.0, "E")]
GUARANTEE = re.compile(r"必ず|確実に|間違いなく|保証します|成果を約束|確実な効果")
AI_WRONG = re.compile(r"Chat\s+GPT|chatgpt|CHATGPT|チャットGPT|ジェミニ|クロード|Bard|Google\s*Gemini")
AI_LIST = re.compile(r"ChatGPT(\s*[/／]\s*)Gemini(\s*[/／]\s*)Claude")
RATE_OK = re.compile(r"^(\d+(\.\d)?%|—)$")


def load_profile(path: Path = PROFILE_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def extract_pptx(path) -> dict:
    """pptx → {図形名: [文字, ...]}（全スライド）。表のセルも含める。python-pptx が必要。"""
    from pptx import Presentation  # 遅延 import

    out: dict = defaultdict(list)
    for slide in Presentation(str(path)).slides:
        for sh in slide.shapes:
            if sh.has_text_frame and sh.text_frame.text.strip():
                out[sh.name].append(sh.text_frame.text.strip())
    return dict(out)


def grade_national(rank: int) -> str:
    for upper, g in NATIONAL_BANDS:
        if rank <= upper:
            return g
    return "?"


def grade_pct(rank: int, pop: int) -> str:
    p = rank / pop * 100
    for upper, g in PCT_BANDS:
        if p < upper or (upper == 100.0 and p <= 100.0):
            return g
    return "?"


def _add(f: list, check: str, sev: str, msg: str):
    f.append({"check": check, "severity": sev, "message": msg})


def _all_text(shapes: dict) -> str:
    return "\n".join(t for ts in shapes.values() for t in ts)


def audit(shapes: dict, rec: dict, profile: dict | None = None, not_judged: list | None = None) -> dict:
    """not_judged: 呼び出し側が判断できなかった項目（正本が未確定など）。1 件でもあり、不合格でなければ判定は『保留』"""
    p = profile or load_profile()
    f: list = []
    text = _all_text(shapes)

    # 1 未差し込み項目
    if "{{" in text or "}}" in text:
        _add(f, "未差し込み", "重大", "差し込み項目 {{…}} が残っている")
    # 2 外部ツール名
    if re.search("semrush", text, re.I):
        _add(f, "外部ツール名", "重大", "Semrush の名前が出ている（『外部の計測基盤』と書く）")
    # 3 自社表記の正本
    for w in p["association_wrong_forms"]:
        if w in text and p["association_name"] not in text:
            _add(f, "協会名", "重大", f"協会名が正本と違う: 『{w}』（正: {p['association_name']}）")
            break
    if "協会" in text and p["association_name"] not in text and not any(w in text for w in p["association_wrong_forms"]):
        _add(f, "協会名", "中", "協会名が正本と一致しない（表記不明）")
    for w in p["address_wrong_forms"]:
        if w in text:
            _add(f, "住所", "中", f"住所のビル名が誤字: 『{w}』（正: {p['address_building']}）")
    # 4 AI 名称の統一
    if AI_WRONG.search(text):
        _add(f, "AI名称", "中", f"AI の名称が統一ルールと違う: {AI_WRONG.search(text).group(0)}")
    seps = {m.group(1) + "|" + m.group(2) for m in AI_LIST.finditer(text)}
    if len(seps) > 1:
        _add(f, "AI名称の区切り", "軽", "対象 AI の区切り（/ と ／、空白）が箇所によって違う")
    # 5 根拠の値との一致（source_fields の全キーは図形名と同じ）
    for key, expect in rec["source_fields"].items():
        got = shapes.get(key)
        if got is None:
            _add(f, "値の一致", "重大", f"{key} が成果物に見つからない")
        elif any(g != expect for g in got):
            _add(f, "値の一致", "重大", f"{key}: 成果物『{got[0]}』≠根拠『{expect}』")
    for key, expect in {"REPORT_ID": f"Report ID：{rec['report_id']}",
                        "COND_VALUE_TARGET": f"{rec['prefecture']} {rec['municipality']}",
                        "FOOTER_LEFT": f"AI 可視性分析レポート［ダイジェスト版］／ {rec['prefecture']} {rec['municipality']}"}.items():
        got = shapes.get(key, [])
        if not got or any(g != expect for g in got):
            _add(f, "値の一致", "重大", f"{key}: 成果物『{got[:1]}』≠根拠『{expect}』")
    for i, r in enumerate(rec["resources"][:3], 1):
        got = shapes.get(f"ASSET_{i}", [])
        if r["asset_name"] != "―" and (not got or got[0] != r["asset_name"]):
            _add(f, "値の一致", "重大", f"ASSET_{i}: 成果物『{got[:1]}』≠根拠『{r['asset_name']}』")
    # 6 根拠の内部整合（評価と順位）
    if grade_national(rec["national_rank"]) != rec["national_grade"]:
        _add(f, "評価と順位", "重大", f"全国 {rec['national_rank']}位 は {grade_national(rec['national_rank'])} のはずが {rec['national_grade']}")
    for lv, key in (("region", "region"), ("prefecture", "prefecture")):
        g = grade_pct(rec[f"{key}_rank"], rec[f"{key}_population"])
        if g != rec[f"{lv}_grade"]:
            _add(f, "評価と順位", "重大", f"{lv}: {rec[key + '_rank']}/{rec[key + '_population']} は {g} のはずが {rec[lv + '_grade']}")
    # 7 母数・集計単位の注記
    scope = " ".join(shapes.get("DEF_VALUE_SCOPE", []))
    if "1,741" not in scope or "1,719" not in scope:
        _add(f, "母数注記", "重大", "出現率（1,741）とランキング（1,719）の集計単位の明記がない")
    foot = " ".join(shapes.get("SCORE_FOOTNOTE", []))
    if "母集団" not in foot:
        _add(f, "母数注記", "中", "出現率の母集団についての注記がない")
    # 8 出現率の書式（0% と欠損の混同を防ぐ：数値か『—』のみ）
    for i in (1, 2, 3):
        for t in shapes.get(f"SCORE_RATE_{i}", []):
            if not RATE_OK.match(t):
                _add(f, "出現率の書式", "重大", f"SCORE_RATE_{i} が数値でも『—』でもない: 『{t}』")
    # 9 成果保証などのリスク表現（免責文は除く）
    body = "\n".join(t for k, ts in shapes.items() if k != "DISCLAIMER" for t in ts)
    m = GUARANTEE.search(body)
    if m:
        _add(f, "リスク表現", "重大", f"成果を保証するような表現: 『{m.group(0)}』")
    if not shapes.get("DISCLAIMER"):
        _add(f, "リスク表現", "重大", "免責の注記がない")
    # 10 社名・連絡先（正本は社長確認済み）
    for w in p.get("company_wrong_forms", []):
        if w in text:
            _add(f, "社名", "重大", f"社名の表記が正本と違う: 『{w}』（正: {p['company_name']}）")
    contact = " ".join(shapes.get("CONTACT_COMPANY", []) + shapes.get("CONTACT_TEL", []) + shapes.get("CONTACT_MAIL", []))
    if p.get("company_name") and p["company_name"] not in contact:
        if not any(w in text for w in p.get("company_wrong_forms", [])):
            _add(f, "社名", "重大", "お問い合わせ先に社名がない、または正本と一致しない")
    if p.get("phone") and p["phone"] not in " ".join(shapes.get("CONTACT_TEL", [])):
        _add(f, "電話", "中", f"電話番号が正本と一致しない・ない（正: {p['phone']}）")
    if p.get("email") and p["email"] not in " ".join(shapes.get("CONTACT_MAIL", [])):
        _add(f, "メール", "中", f"メールアドレスが正本と一致しない・ない（正: {p['email']}）")
    verdict = "不合格" if any(x["severity"] in SEV_FAIL for x in f) else ("合格（指摘あり）" if f else "合格")
    nj = list(not_judged or [])
    if nj and verdict != "不合格":
        verdict = "保留"  # 判断できなかった項目が残る間は合格にせず、人が決める
    return {"verdict": verdict, "findings": f, "not_judged": nj}
