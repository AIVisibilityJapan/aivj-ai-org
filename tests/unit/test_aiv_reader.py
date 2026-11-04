"""AI-03-01 の読み取り道具の試験（T4-01〜03・07）。架空データを一時ファイルに作って使う。"""
import hashlib, importlib.util, json, pathlib, pytest

spec = importlib.util.spec_from_file_location("vr", pathlib.Path(__file__).parents[2] / "src/aiv/values_reader.py")
vr = importlib.util.module_from_spec(spec); spec.loader.exec_module(vr)


def rec(name="架空市", mid="MUNI_000001", rate="0.0%", asset="架空の滝"):
    sf = {"SCORE_TH_2": "架空ブロック", "SCORE_TH_3": "架空県", "SCORE_RATE_1": rate, "SCORE_RATE_2": "1.0%", "SCORE_RATE_3": "2.0%",
          "SCORE_GRADE_1": "E", "SCORE_GRADE_2": "D", "SCORE_GRADE_3": "C", "SCORE_SUB_1": "b1", "SCORE_SUB_2": "b2", "SCORE_SUB_3": "b3",
          "NEG_STATUS": "検出あり", "NEG_COUNT": "7件"}
    return {"prefecture": "架空県", "municipality": name, "municipality_id": mid, "official_code": "000001", "report_id": "AIV-000001-2026Q4",
            "national_rank": 1000, "national_grade": "E", "national_band": "b1", "region_header": "架空ブロック", "region_rank": 5,
            "region_population": 10, "region_grade": "D", "region_band": "b2", "prefecture_rank": 3, "prefecture_population": 9,
            "prefecture_grade": "C", "prefecture_band": "b3", "national_rate": rate, "region_rate": "1.0%", "prefecture_rate": "2.0%",
            "negative_count": 7, "negative_status": "検出あり", "source_fields": sf,
            "resources": [{"asset_name": asset, "source": "X"}, {"asset_name": "―", "source": "DASH"}, {"asset_name": "―", "source": "DASH"}],
            "selector_metadata": {"selector_version": "1.5.49"}}


def setup(tmp_path, records):
    p = tmp_path / "v.json"; p.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    pins = {"report_values": {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "selector": "1.5.50"},
            "population": {"appearance": 1741, "apa_rank": 1719}}
    return p, pins


def test_reads_and_keeps_values_verbatim(tmp_path):
    p, pins = setup(tmp_path, [rec()])
    recs, src = vr.load_values(p, pins)
    out = vr.organize(vr.get_municipality(recs, "架空市"), src, pins)
    assert out["report_fields"]["SCORE_RATE_2"] == "1.0%" and out["provenance"]["sha256"] == src["sha256"]
    assert out["metrics"]["apa_rank"]["national"]["population"] == 1719  # 集計単位を明示


def test_zero_and_missing_are_not_confused(tmp_path):  # T4-03
    p, pins = setup(tmp_path, [rec(rate="0.0%")])
    recs, src = vr.load_values(p, pins)
    out = vr.organize(recs[0], src, pins)
    assert out["metrics"]["appearance_rate"]["scopes"]["national"]["state"] == "UNVERIFIED_ZERO"
    assert out["metrics"]["appearance_rate"]["scopes"]["region"]["state"] == "FORMAL_VALUE"
    assert [r["state"] for r in out["resources"]] == ["FORMAL_VALUE", "NOT_AVAILABLE", "NOT_AVAILABLE"]
    assert out["resources"][1]["name"] is None  # 『―』を値にしない


def test_sha_mismatch_stops(tmp_path):  # T4-02 fail closed
    p, pins = setup(tmp_path, [rec()])
    p.write_text(p.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(vr.ReaderStop):
        vr.load_values(p, pins)


def test_unset_pin_stops(tmp_path):
    p, pins = setup(tmp_path, [rec()]); pins["report_values"]["sha256"] = None
    with pytest.raises(vr.ReaderStop):
        vr.load_values(p, pins)


def test_unknown_or_duplicate_municipality_stops(tmp_path):
    with pytest.raises(vr.ReaderStop):
        vr.get_municipality([rec()], "存在しない市")
    with pytest.raises(vr.ReaderStop):
        vr.get_municipality([rec(), rec(mid="MUNI_000002")], "架空市")


def test_inconsistent_record_stops(tmp_path):
    r = rec(); r["source_fields"]["SCORE_RATE_1"] = "9.9%"
    p, pins = setup(tmp_path, [r]); recs, src = vr.load_values(p, pins)
    with pytest.raises(vr.ReaderStop):
        vr.organize(recs[0], src, pins)


def test_source_file_is_not_modified(tmp_path):  # T4-07
    p, pins = setup(tmp_path, [rec()]); b = hashlib.sha256(p.read_bytes()).hexdigest()
    recs, src = vr.load_values(p, pins); vr.organize(recs[0], src, pins)
    assert hashlib.sha256(p.read_bytes()).hexdigest() == b
