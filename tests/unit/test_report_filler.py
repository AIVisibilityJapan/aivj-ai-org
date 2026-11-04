"""AI-03-05 の差し込み道具の試験。ひな形は試験内で架空に作る（実データなし）。"""
import importlib.util, pathlib, pytest
from pptx import Presentation
from pptx.util import Inches

spec = importlib.util.spec_from_file_location("rf", pathlib.Path(__file__).parents[2] / "src/aiv/report_filler.py")
rf = importlib.util.module_from_spec(spec); spec.loader.exec_module(rf)


def make_template(path, texts):
    prs = Presentation(); s = prs.slides.add_slide(prs.slide_layouts[6])
    for name, t in texts.items():
        tb = s.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1)); tb.name = name
        p = tb.text_frame.paragraphs[0]
        for i, part in enumerate(t.replace("}}", "}}\0").replace("{{", "\0{{").split("\0")):  # 差し込み項目を複数 run に分割
            if part:
                r = p.add_run(); r.text = part
    prs.save(str(path))


ORG = {"municipality": {"prefecture": "架空県", "municipality": "架空市", "report_id": "AIV-1"},
       "report_fields": {k: "x" for k in ["SCORE_TH_2", "SCORE_RATE_1", "SCORE_RATE_2", "SCORE_RATE_3", "SCORE_GRADE_1", "SCORE_GRADE_2",
                                          "SCORE_GRADE_3", "SCORE_SUB_1", "SCORE_SUB_2", "SCORE_SUB_3", "HIGH_VALUE", "LOW_VALUE",
                                          "NEG_STATUS", "NEG_COUNT", "COMP_R2C1", "COMP_R3C1", "COMP_R1C2", "COMP_R1C3", "COMP_R1C4",
                                          "COMP_R2C2", "COMP_R2C3", "COMP_R2C4", "COMP_R3C2", "COMP_R3C3", "COMP_R3C4"]},
       "resources": [{"no": 1, "name": "滝", "display": "滝"}, {"no": 2, "name": None, "display": "―"}, {"no": 3, "name": None, "display": ""}]}
ORG["report_fields"].update({"SCORE_TH_2": "架空ブロック", "SCORE_SUB_2": "一行目\n二行目"})
PAR = {"issue_date": "2026年1月1日", "next_issue_date": "2026年4月"}


def run(tmp_path, texts, org=ORG, **kw):
    t = tmp_path / "t.pptx"; make_template(t, texts)
    out = tmp_path / "o.pptx"
    r = rf.fill(t, org, PAR, out, **kw)
    return t, out, {sh.name: [p.text for p in sh.text_frame.paragraphs] for sh in Presentation(str(out)).slides[0].shapes}


def test_fills_split_runs_and_region_block_name(tmp_path):
    t, out, got = run(tmp_path, {"A": "{{municipality.prefecture_name}} {{municipality.name}}", "B": "{{municipality.region_block_name}}ブロック"})
    assert got["A"] == ["架空県 架空市"] and got["B"] == ["架空ブロック"]  # 『ブロック』の重複なし


def test_newline_in_value_becomes_paragraphs(tmp_path):
    _, _, got = run(tmp_path, {"A": "{{report.apa.overall.region_block.grade_range}}"})
    assert got["A"] == ["一行目", "二行目"]


def test_template_not_modified_and_no_overwrite(tmp_path):
    t, out, _ = run(tmp_path, {"A": "{{report.id}}"})
    assert "{{report.id}}" in [p.text for p in Presentation(str(t)).slides[0].shapes[0].text_frame.paragraphs][0]
    with pytest.raises(rf.FillStop):
        rf.fill(t, ORG, PAR, t)


def test_unknown_token_stops(tmp_path):
    with pytest.raises(rf.FillStop):
        run(tmp_path, {"A": "{{未知の項目}}"})


def test_missing_resource_uses_formal_dash_but_empty_stops(tmp_path):  # 欠損は正式データの表示『―』。空は埋めずに止める
    _, _, got = run(tmp_path, {"A": "{{appearance.asset.top_2.display}}"})
    assert got["A"] == ["―"]
    with pytest.raises(rf.FillStop):
        run(tmp_path, {"A": "{{appearance.asset.top_3.display}}"})


def test_missing_params_stop(tmp_path):
    t = tmp_path / "t.pptx"; make_template(t, {"A": "x"})
    with pytest.raises(rf.FillStop):
        rf.fill(t, ORG, {"issue_date": "", "next_issue_date": "y"}, tmp_path / "o.pptx")


def test_override_for_fixed_text_and_missing_target_stops(tmp_path):
    _, _, got = run(tmp_path, {"D": "旧い測定期間"}, overrides={"D": "新しい期間"})
    assert got["D"] == ["新しい期間"]
    with pytest.raises(rf.FillStop):
        run(tmp_path, {"D": "x"}, overrides={"ZZZ": "y"})
