"""R1 T1（値取り出し）の試験。合成の小さな Mart だけを使い、実データには触れない。"""
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import aiv_r1_values as T  # noqa: E402

CATS = {"PUR_01": "温泉", "PUR_02": "自然"}
PREF = {"M1": "P01", "M2": "P01", "M3": "P01", "M4": "P01", "M5": "P02", "M6": "P02"}
# 出現する質問の割合を自治体ごとに決める（M5 と M6 は同率にする）
PICK = {"M1": lambda i: i % 2 == 0, "M2": lambda i: i % 3 == 0, "M3": lambda i: i % 5 == 0,
        "M4": lambda i: i % 7 == 0, "M5": lambda i: i % 4 == 0, "M6": lambda i: i % 4 == 0}
APA_RANK = {"M1": 1, "M2": 2, "M3": 3, "M4": 4, "M5": 5, "M6": 6}


def build(tmp: Path):
    qs = []  # (id, scope, target, cat, traveler, season, itin)
    k = 0
    for scope, target in [("national", "A00"), ("region_block", "B01"), ("prefecture", "P01"), ("prefecture", "P02")]:
        for j in range(40):
            qs.append((f"Q{k:03d}", scope, target, "PUR_01" if j % 2 == 0 else "PUR_02", ("solo", "family")[j % 2],
                       ("spring", "summer")[(j // 2) % 2], ("day", "stay")[(j // 4) % 2]))
            k += 1
    a = sqlite3.connect(tmp / "app.db")
    a.executescript("""
    create table appearance_municipality(municipality_id, official_municipality_code, municipality_name, municipality_type, prefecture_code, prefecture_name, region_block_id, region_block_name, measurement_target_flag, reporting_target_flag, reference_only_flag, special_ward_flag, population_version);
    create table appearance_category(category_id, category_name, category_slug, valid_response_count_all_scopes, category_contract_source);
    create table appearance_question(question_id, question_text, category_id, scope, scope_target_id, traveler_type, season, itinerary, question_version, provenance_id);
    create table appearance_question_municipality(question_id, municipality_id, min_candidate_rank, category_id, scope, scope_target_id, traveler_type, season, itinerary, measurement_origin, resolution_status, provenance_id);
    create table appearance_rate(rate_id, municipality_id, scope, scope_target_id, category_id, metric_type, appearance_count, valid_response_count, appearance_rate, formal_or_derived, value_status);
    create table appearance_dimension_rate(measurement_version, municipality_id, dimension_type, dimension_value, appearance_count, valid_response_count, appearance_rate, formal_or_derived, value_status, provenance_id);
    create table appearance_build_metadata(reporting_target_count, valid_response_count);
    create table appearance_measurement(formal_rank_cutoff);
    create table municipality_asset_top5(municipality_id, municipality_name, asset_rank, asset_id, canonical_asset_name, question_count, municipality_appearance_question_count, share, metric_scope);
    create table appearance_asset_occurrence(municipality_id, metric_scope, asset_id, question_id, candidate_rank, category_id, scope, scope_target_id, candidate_text, canonical_asset_name);
    """)
    a.execute("insert into appearance_build_metadata values (6, ?)", (len(qs),))
    a.execute("insert into appearance_measurement values (3)")
    for c, n in CATS.items():
        a.execute("insert into appearance_category values (?,?,?,?,?)", (c, n, c, 0, ""))
    for m, p in PREF.items():
        a.execute("insert into appearance_municipality values (?,?,?,?,?,?,?,?,?,?,?,?,?)", (f"MUNI_{m}", "0", f"市{m}", "市", p, f"県{p}", "B01", "ブロック1", 1, 1, 0, 0, "v"))
    for q in qs:
        a.execute("insert into appearance_question values (?,?,?,?,?,?,?,?,?,?)", (q[0], "", q[3], q[1], q[2], q[4], q[5], q[6], "v", ""))
    appear = defaultdict(set)
    for i, q in enumerate(qs):
        for m in PREF:
            if PICK[m](i) and (q[1] != "prefecture" or q[2] == PREF[m]):  # 自県の質問だけに出る（例外なし）
                appear[m].add(q[0])
                a.execute("insert into appearance_question_municipality values (?,?,?,?,?,?,?,?,?,?,?,?)", (q[0], f"MUNI_{m}", 2, q[3], q[1], q[2], q[4], q[5], q[6], "", "", ""))
    rid = 0

    def put(m, scope, target, cat, metric, qsel):
        nonlocal rid
        rid += 1
        n = len(qsel)
        c = sum(1 for q in qsel if q[0] in appear[m])
        a.execute("insert into appearance_rate values (?,?,?,?,?,?,?,?,?,?,?)", (rid, f"MUNI_{m}", scope, target, cat or "", metric, c, n, c / n if n else None, "FORMAL", "EXPLICIT_ZERO" if c == 0 else "VALUE"))

    for m, p in PREF.items():
        for scope, target in [("national", "A00"), ("region_block", "B01"), ("prefecture", p)]:
            sel = [q for q in qs if q[1] == scope and q[2] == target]
            put(m, scope, target, None, "overall_scope_rate", sel)
            for c in CATS:
                put(m, scope, target, c, "category_scope_rate", [q for q in sel if q[3] == c])
        put(m, "all_scopes", "__ALL_SCOPES__", None, "overall_all_scopes_rate", qs)
        for c in CATS:
            put(m, "all_scopes", "__ALL_SCOPES__", c, "category_all_scopes_rate", [q for q in qs if q[3] == c])
        for d, idx in (("traveler", 4), ("season", 5), ("itinerary", 6)):
            for v in sorted({q[idx] for q in qs}):
                sel = [q for q in qs if q[idx] == v]
                c = sum(1 for q in sel if q[0] in appear[m])
                a.execute("insert into appearance_dimension_rate values (?,?,?,?,?,?,?,?,?,?)", ("v", f"MUNI_{m}", d, v, c, len(sel), c / len(sel), "FORMAL", "VALUE", ""))
    a.execute("insert into municipality_asset_top5 values ('MUNI_M1','市M1',1,'A1','温泉街',10,50,0.2,'all')")
    a.commit()
    a.close()

    b = sqlite3.connect(tmp / "apa.db")
    b.executescript("""
    create table municipality_master(municipality_id, municipality_name, prefecture);
    create table rankings(municipality_id, evaluation_id, rank);
    create table municipality_comparisons(municipality_id, evaluation_id, comparison_id, stage, round, opponent_id, opponent_name, result, recommended_reason, not_recommended_reason, self_positive_reason, self_negative_reason, opponent_positive_reason, opponent_negative_reason);
    create table municipality_negative_summary(municipality_id, negative_reason_count_total_raw, negative_reason_unique_exact_total, evaluations_with_negative);
    create table negative_summary(municipality_id, evaluation_id, negative_reason_count_raw, negative_reason_unique_exact_count, loss_count);
    create table negative_reasons(municipality_id, evaluation_id, comparison_id, opponent_id, opponent_name, stage, round, negative_reason, normalized_negative_reason);
    """)
    for m, p in PREF.items():
        b.execute("insert into municipality_master values (?,?,?)", (f"MUNI_{m}", f"市{m}", f"県{p}"))
        for e in T.EVAL_IDS:
            b.execute("insert into rankings values (?,?,?)", (f"MUNI_{m}", e, APA_RANK[m]))
    b.execute("insert into municipality_comparisons values ('MUNI_M3','overall','C1','s',1,'MUNI_M2','市M2','loss','r','n','sp','sn','op','on')")
    b.execute("insert into municipality_negative_summary values ('MUNI_M3',5,4,2)")
    b.execute("insert into negative_summary values ('MUNI_M3','overall',3,3,1)")
    b.execute("insert into negative_reasons values ('MUNI_M3','overall','C1','MUNI_M2','市M2','s',1,'遠い','遠い')")
    b.commit()
    b.close()
    return qs


@pytest.fixture()
def marts(tmp_path):
    build(tmp_path)
    return tmp_path


def run_one(marts, mid, expect=None):
    pins = {"appearance_mart": {"path": str(marts / "app.db"), "sha256": "x"}, "apa_report_mart": {"path": str(marts / "apa.db"), "sha256": "y"}}
    outs = T.run(marts / "app.db", marts / "apa.db", [mid], marts / "out", pins, expect=expect)
    return outs[0], json.loads((outs[0] / "values.json").read_text(encoding="utf-8"))


def test_outputs_and_values(marts):
    out, v = run_one(marts, "MUNI_M3")
    for f in ("values.json", "slot_status.csv", "manifest.json", "evidence/negative_reasons.csv"):
        assert (out / f).exists()
    s = v["slots"]
    assert s["G01.period"]["value"] == "2026年9月1日～9月30日"
    assert s["G03.overall.national"]["status"] == "VALUE"
    assert s["G03.overall.national"]["value"] == pytest.approx(8 / 40)  # i%5==0 を 40 問中 8 問
    assert s["G03.overall.national"]["n"] == 40
    assert s["G10.negative.total"]["value"] == 5


def test_unmeasured_are_null(marts):
    _, v = run_one(marts, "MUNI_M3")
    s = v["slots"]
    for sid in ("G04.appearance.overall.national.Gemini", "G04.appearance.overall.national.Claude", "G11.spot_apa", "G05.change.appearance.overall.national"):
        assert s[sid]["status"] == "NOT_MEASURED" and s[sid]["value"] is None
    assert s["G04.appearance.overall.national.ChatGPT"]["status"] == "VALUE"
    assert all(x["value"] is None for x in s.values() if x["status"] not in ("VALUE", "EXPLICIT_ZERO"))


def test_insufficient_sample_and_zero():
    # 30 未満は値を出さない。0 件は EXPLICIT_ZERO
    s = T.derived_slot(3, 20, "x")
    assert s["status"] == "INSUFFICIENT_SAMPLE" and s["value"] is None
    assert T.derived_slot(0, 40, "x")["status"] == "EXPLICIT_ZERO"
    assert T.derived_slot(0, 0, "x")["status"] == "NO_FORMAL_ROW"
    assert T.derived_slot(4, 40, "x")["value"] == pytest.approx(0.1)


def test_rank_ties_are_same_rank():
    r = T.competition_ranks({"a": 0.5, "b": 0.4, "c": 0.4, "d": 0.1})
    assert r == {"a": 1, "b": 2, "c": 2, "d": 4}


def test_appearance_neighbors_strictly_higher_nearest(marts):
    _, v = run_one(marts, "MUNI_M4")  # 全国の率 M4 は 6/40。より高い自治体は M1 M2 M3 と M5 M6 など
    s = v["slots"]
    me = s["G03.overall.national"]["value"]
    near = [s[f"G03.near.national.{j}"]["value"] for j in (1, 2, 3)]
    assert all(n["rate"] > me for n in near if n["side"] == "higher")
    # 近い順に 3 件（率が高い側の中で自分に最も近いもの）
    higher_rates = sorted({x["rate"] for x in near})
    assert len(near) == 3


def test_apa_neighbors_rank_top_and_fill_lower(marts):
    _, v = run_one(marts, "MUNI_M1")  # 1 位: 上位がないので下位から 3 件
    s = v["slots"]
    names = [s[f"G09.overall.national.near{j}"]["value"]["name"] for j in (1, 2, 3)]
    assert names == ["市M2", "市M3", "市M4"]
    assert all(s[f"G09.overall.national.near{j}"]["value"]["side"] == "lower" for j in (1, 2, 3))
    _, v = run_one(marts, "MUNI_M5")
    names = [v["slots"][f"G09.overall.national.near{j}"]["value"]["name"] for j in (1, 2, 3)]
    assert names == ["市M2", "市M3", "市M4"]  # 上位側 3 件


def test_direct_reason_only_when_record_exists(marts):
    _, v = run_one(marts, "MUNI_M3")
    s = v["slots"]
    # 近接は順位順: near1=M1（記録なし）, near2=M2（直接対戦あり）
    assert s["G09.overall.national.near2.reason"]["status"] == "VALUE"
    assert s["G09.overall.national.near1.reason"]["status"] == "NO_FORMAL_ROW"  # 記録なし → 「—」


def test_region_block_rank_and_band(marts):
    _, v = run_one(marts, "MUNI_M3")
    r = v["slots"]["G08.rank.overall.region_block"]
    assert r["value"] == 3 and r["population"] == 6
    assert r["band"]["grade"] in ("A++", "A+", "A", "B", "C", "D", "E")
    assert v["slots"]["G08.rank.overall.prefecture"]["population"] == 4


def test_band_edges():
    assert T.band(1, 1719)["grade"] == "A++"
    assert T.band(1719, 1719)["grade"] == "E"
    assert T.nat_band(33)["grade"] == "A++" and T.nat_band(34)["grade"] == "A+" and T.nat_band(501)["grade"] == "E"


def test_reproduction_gate_catches_mismatch(marts):
    a = sqlite3.connect(marts / "app.db")
    a.execute("update appearance_rate set appearance_count=appearance_count+1 where rowid=1")
    a.commit()
    a.close()
    with pytest.raises(T.StopError):
        run_one(marts, "MUNI_M3")


def test_count_gate_stops_on_unexpected_counts(marts):
    with pytest.raises(T.StopError):
        run_one(marts, "MUNI_M3", expect={"appearance_municipality": 1747})


def test_not_overwriting_existing_output(marts):
    out, _ = run_one(marts, "MUNI_M3")
    with pytest.raises(FileExistsError):
        T.write_outputs(out, {"meta": {}, "slots": {}, "evidence": {}, "notes": []}, {}, T.Gates(), {}, None)


def test_inputs_unchanged(marts):
    before = (marts / "app.db").read_bytes()
    run_one(marts, "MUNI_M3")
    assert (marts / "app.db").read_bytes() == before


def test_unknown_id_stops(marts):
    with pytest.raises(T.StopError):
        run_one(marts, "MUNI_ZZZ")


def test_norm_id():
    assert T.norm_id("304018") == "MUNI_304018" and T.norm_id("MUNI_304018") == "MUNI_304018"


def test_accept38_compare_detects_match_and_diff(marts):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import aiv_r1_values_accept38 as A
    _, v = run_one(marts, "MUNI_M3")
    s = v["slots"]
    ref = {"municipality_id": "MUNI_M3", "municipality": "市M3", "national_rank": 3, "national_grade": s["G08.rank.overall.national"]["band"]["grade"],
           "region_rank": 3, "region_population": 6, "region_grade": s["G08.rank.overall.region_block"]["band"]["grade"],
           "prefecture_rank": 3, "prefecture_population": 4, "prefecture_grade": s["G08.rank.overall.prefecture"]["band"]["grade"],
           "national_rate": A.pct(s["G03.overall.national"]["value"]), "region_rate": A.pct(s["G03.overall.region_block"]["value"]),
           "prefecture_rate": A.pct(s["G03.overall.prefecture"]["value"]), "negative_count": 5,
           "source_fields": {"HIGH_VALUE": A.cats(s, "G03.high_categories"), "LOW_VALUE": A.cats(s, "G03.low_categories"),
                             "COMP_R1C2": "市M1（県P01）", "COMP_R1C3": "市M2（県P01）", "COMP_R1C4": "市M4（県P01）",
                             "COMP_R2C1": "温泉", "COMP_R2C2": "x", "COMP_R2C3": "x", "COMP_R2C4": "x",
                             "COMP_R3C1": "温泉", "COMP_R3C2": "x", "COMP_R3C3": "x", "COMP_R3C4": "x"}}
    rows = A.compare(ref, v)
    ok = {r["item"]: r["match"] for r in rows}
    assert ok["APA総合 全国順位"] == "OK" and ok["出現率 national"] == "OK" and ok["ネガティブ件数"] == "OK"
    assert ok["競合 総合 近接1"] == "OK" and ok["競合 総合 近接3"] == "OK"
    ref["negative_count"] = 6
    assert {r["item"]: r["match"] for r in A.compare(ref, v)}["ネガティブ件数"] == "DIFF"


def test_run_probe_counts_models_and_times(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import aiv_r1_run_probe as P
    p = tmp_path / "output.jsonl"
    rows = [{"custom_id": "a", "response": {"body": {"model": "m1", "created": 1785888000}}},
            {"custom_id": "b", "response": {"body": {"model": "m1", "created": 1785974400}}},
            {"custom_id": "b", "response": {"body": {"model": "m2", "created_at": 1785900000}}}]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
    r = P.scan_file(p)
    assert r["lines"] == 4 and r["bad"] == 1 and r["models"] == {"m1": 2, "m2": 1} and r["dup_ids"] == 1
    assert r["times"] == (1785888000.0, 1785974400.0)
