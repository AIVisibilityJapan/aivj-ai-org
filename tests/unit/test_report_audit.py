"""AI-06-06 監査の検査器の試験（T4-05/T4-06/T4-07）。架空の自治体『架空市』だけを使い、実データは使わない。"""
import copy
import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location("ra", pathlib.Path(__file__).parents[2] / "src/audit/report_audit.py")
ra = importlib.util.module_from_spec(spec); spec.loader.exec_module(ra)
P = ra.load_profile()

SRC = {"SCORE_TH_2": "架空ブロック", "SCORE_TH_3": "架空県", "SCORE_RATE_1": "1.2%", "SCORE_RATE_2": "5.0%",
       "SCORE_RATE_3": "9.9%", "SCORE_GRADE_1": "B", "SCORE_GRADE_2": "A++", "SCORE_GRADE_3": "A+",
       "SCORE_SUB_1": "101〜200位", "SCORE_SUB_2": "帯2", "SCORE_SUB_3": "帯3", "HIGH_VALUE": "自然景観",
       "LOW_VALUE": "都市観光", "NEG_STATUS": "検出あり", "NEG_COUNT": "10件", "COMP_R1C1": "総合",
       "COMP_R1C2": "甲市（乙県）"}
REC = {"prefecture": "架空県", "municipality": "架空市", "report_id": "AIV-000000-2026Q4", "source_fields": SRC,
       "national_rank": 150, "national_grade": "B", "region_rank": 5, "region_population": 100, "region_grade": "A++",
       "prefecture_rank": 5, "prefecture_population": 50, "prefecture_grade": "A+",
       "resources": [{"asset_name": "架空の滝"}, {"asset_name": "架空の浜"}, {"asset_name": "―"}]}


def clean():
    s = {k: [v] for k, v in SRC.items()}
    s.update({"REPORT_ID": ["Report ID：AIV-000000-2026Q4"], "COND_VALUE_TARGET": ["架空県 架空市"],
              "FOOTER_LEFT": ["AI 可視性分析レポート［ダイジェスト版］／ 架空県 架空市"],
              "ASSET_1": ["架空の滝"], "ASSET_2": ["架空の浜"],
              "DEF_VALUE_SCOPE": ["出現率：全国1,741自治体／自治体ランキング：全国1,719自治体"],
              "SCORE_FOOTNOTE": ["※出現率は各基準で母集団が異なります。"],
              "COND_VALUE_AI": ["ChatGPT / Gemini / Claude"], "DEF_VALUE_AI": ["ChatGPT / Gemini / Claude"],
              "DEF_VALUE_METHOD": ["一般社団法人AI検索可視性標準化協会認定の測定手法に基づく。"],
              "CONTACT_ADDRESS": ["大阪府大阪市北区梅田2-2-2 ヒルトンプラザウエスト19階"],
              "CONTACT_COMPANY": ["AI Visibility Japan株式会社"], "CONTACT_TEL": ["TEL：06-7777-6718"], "CONTACT_MAIL": ["E-mail：info@aivj.co.jp"],
              "DISCLAIMER": ["（注）数値は参考情報であり、将来の成果を保証しません。"]})
    return s, copy.deepcopy(REC)


def test_clean_passes_without_false_positive():
    s, r = clean()
    out = ra.audit(s, r, P)
    assert out["verdict"] == "合格" and out["findings"] == []


# 混ぜる不備: (名前, 変更関数, 期待する検査名)
def _set(key, val):
    return lambda s, r: s.__setitem__(key, [val])


DEFECTS = [
    ("差し込み項目の残り", _set("HIGH_VALUE", "{{report.appearance.high_categories.display}}"), "未差し込み"),
    ("Semrush 名の漏れ", _set("DEF_VALUE_METHOD", "Semrush の計測に基づく。"), "外部ツール名"),
    ("協会名から『検索』が抜ける", _set("DEF_VALUE_METHOD", "一般社団法人 AI 可視性標準化協会認定の測定手法。"), "協会名"),
    ("住所の誤字", _set("CONTACT_ADDRESS", "大阪府大阪市北区梅田2-2-2 ヒルトンプラサウ工スト19階"), "住所"),
    ("社名の空白（全角）", _set("CONTACT_COMPANY", "AI Visibility Japan\u3000株式会社"), "社名"),
    ("社名の欠落", _set("CONTACT_COMPANY", "別の会社"), "社名"),
    ("電話番号の誤り", _set("CONTACT_TEL", "TEL：06-0000-0000"), "電話"),
    ("メールの誤り", _set("CONTACT_MAIL", "E-mail：info@example.com"), "メール"),
    ("連絡先の欠落", lambda s, r: s.pop("CONTACT_TEL"), "電話"),
    ("AI 名称の誤り", _set("DEF_VALUE_AI", "Chat GPT / Gemini / Claude"), "AI名称"),
    ("AI 名称の区切りの揺れ", _set("DEF_VALUE_AI", "ChatGPT／Gemini／Claude"), "AI名称の区切り"),
    ("値の取り違え（出現率）", _set("SCORE_RATE_1", "2.2%"), "値の一致"),
    ("競合の取り違え", _set("COMP_R1C2", "丙市（丁県）"), "値の一致"),
    ("観光資源の取り違え", _set("ASSET_1", "別の滝"), "値の一致"),
    ("別の自治体名が混入", _set("FOOTER_LEFT", "AI 可視性分析レポート［ダイジェスト版］／ 架空県 別市"), "値の一致"),
    ("項目の欠落", lambda s, r: s.pop("NEG_COUNT"), "値の一致"),
    ("評価と順位の食い違い（根拠側）", lambda s, r: r.__setitem__("national_grade", "A"), "評価と順位"),
    ("集計単位（1,719/1,741）の注記なし", _set("DEF_VALUE_SCOPE", "全国1,741自治体"), "母数注記"),
    ("母集団の注記なし", _set("SCORE_FOOTNOTE", "※注記。"), "母数注記"),
    ("欠損を 0 や空で表示", _set("SCORE_RATE_2", "未取得"), "出現率の書式"),
    ("成果保証の表現", _set("HIGH_VALUE", "必ず順位が上がります"), "リスク表現"),
    ("免責の欠落", lambda s, r: s.pop("DISCLAIMER"), "リスク表現"),
]


def test_each_injected_defect_is_detected_by_the_right_check():
    missed = []
    for name, mut, check in DEFECTS:
        s, r = clean(); mut(s, r)
        out = ra.audit(s, r, P)
        if not any(x["check"] == check for x in out["findings"]):
            missed.append(name)
        # 軽以外の不備は必ず不合格になる
        if check != "AI名称の区切り":
            assert out["verdict"] == "不合格", name
    assert not missed, f"検出漏れ: {missed}"  # 検出率 100%


def test_separator_drift_is_minor_only():
    s, r = clean(); s["DEF_VALUE_AI"] = ["ChatGPT／Gemini／Claude"]
    out = ra.audit(s, r, P)
    assert out["verdict"] == "合格（指摘あり）"


def test_audit_never_modifies_inputs():  # T4-06/07: 指摘のみ・成果物と根拠を書き換えない
    s, r = clean(); s["SCORE_RATE_1"] = ["9.9%"]
    s0, r0 = copy.deepcopy(s), copy.deepcopy(r)
    ra.audit(s, r, P)
    assert s == s0 and r == r0


def test_contacts_are_confirmed_and_judged():  # 社長確認済みの正本で判定する
    assert P["phone"] == "06-7777-6718" and P["email"] == "info@aivj.co.jp" and P["company_name"] == "AI Visibility Japan株式会社"
    s, r = clean()
    assert ra.audit(s, r, P)["verdict"] == "合格"
