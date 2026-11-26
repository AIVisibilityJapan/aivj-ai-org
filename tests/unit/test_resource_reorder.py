"""aiv_resource_reorder_v1.py の回帰テスト（合成データ。実データ・private は使わない）。"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "aiv_resource_reorder_v1.py"
if not SCRIPT.exists():
    SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "aiv_resource_reorder_v1.py"

MASTER = ["asset_id", "canonical_name", "canonical_name_normalized", "resource_type", "resource_subtype", "primary_municipality_id",
          "verified_municipality_ids", "verification_status", "asset_status", "first_source", "first_source_asset_id", "first_seen_measurement",
          "last_verified_at", "merge_basis", "merge_confidence", "created_at", "updated_at", "notes"]
REL = ["asset_id", "municipality_id", "relation_type", "verification_status", "is_primary", "evidence_id", "relation_status", "original_asset_id",
       "original_relation_type", "updated_at", "notes"]
ALIAS = ["asset_id", "alias", "alias_scope", "municipality_id", "evaluation_id", "context_rule", "verification_status", "source", "alias_status",
         "original_asset_id", "original_alias_scope", "created_at", "updated_at", "notes"]
SLOT = ["municipality_id", "municipality_name", "display_slot", "common_asset_id", "canonical_name", "source_tier", "source_namespace",
        "source_record_id", "appearance_candidate_rank", "apa_source_information", "dedup_reason", "promotion_reason", "resource_scope",
        "relation_type", "relation_status", "relation_evidence_id", "verification_status", "asset_status"]
SPEC = ["op", "municipality_id", "asset_id", "name", "slot", "source_tier", "source_record_ids", "new_resource_type", "new_resource_subtype",
        "address_original", "address_municipality", "official_evidence_url", "evidence_kind", "audit_ref", "president_confirmation_ref"]


def w(path, cols, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        d = csv.DictWriter(f, cols)
        d.writeheader()
        for r in rows:
            d.writerow({c: r.get(c, "") for c in cols})


def asset(aid, name, mun, notes=""):
    return dict(asset_id=aid, canonical_name=name, canonical_name_normalized=name, resource_type="spot", resource_subtype="temple",
                primary_municipality_id=mun, verified_municipality_ids=mun, verification_status="VERIFIED", asset_status="ACTIVE",
                first_source="T", first_source_asset_id=aid, last_verified_at="2026-08-01", merge_basis="T", merge_confidence="HIGH",
                created_at="x", updated_at="x", notes=notes)


def relation(aid, mun, rtype, ev):
    return dict(asset_id=aid, municipality_id=mun, relation_type=rtype, verification_status="VERIFIED", is_primary="TRUE", evidence_id=ev,
                relation_status="ACTIVE", original_asset_id=aid, original_relation_type=rtype, updated_at="x", notes="t")


def slot(mun, name, n, aid="", cname="", ev=""):
    r = dict(municipality_id=mun, municipality_name=name, display_slot=str(n))
    if aid:
        r.update(common_asset_id=aid, canonical_name=cname, source_tier="APA_RESOURCE", source_namespace="apa.reason", source_record_id="r",
                 apa_source_information="x", dedup_reason="UNIQUE_COMMON_ID", promotion_reason="P", resource_scope="LOCAL",
                 relation_type="SELF_RESOURCE", relation_status="ACTIVE", relation_evidence_id=ev, verification_status="VERIFIED", asset_status="ACTIVE")
    else:
        r.update(promotion_reason="NO_ELIGIBLE_CANDIDATE")
    return r


@pytest.fixture()
def env(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    # 甲町(900001): 枠1=X(SELF), 枠2=Y(SELF), 枠3=空 / 資産 Z は REGIONAL_CONTEXT。乙町(900002): 枠1=W、"NA" という値を持つ行あり
    w(base / "common_tourism_asset_master_v1_0_1.csv", MASTER, [
        asset("A_X", "甲寺", "900001"), asset("A_Y", "甲山", "900001"), asset("A_Z", "乙寺", "900001"), asset("A_W", "乙町城", "900002", notes="NA"),
        asset("A_NA", "NA", "900002")])
    w(base / "common_asset_municipality_relation_v1_0_1.csv", REL, [
        relation("A_X", "900001", "SELF_RESOURCE", "E_X"), relation("A_Y", "900001", "SELF_RESOURCE", "E_Y"),
        relation("A_Z", "900001", "REGIONAL_CONTEXT", "E_Z"), relation("A_W", "900002", "SELF_RESOURCE", "E_W"),
        relation("A_NA", "900002", "SELF_RESOURCE", "E_NA")])
    w(base / "common_tourism_asset_alias_v1_0_1.csv", ALIAS, [
        dict(asset_id="A_X", alias="甲寺", alias_scope="MUNICIPALITY", municipality_id="MUNI_900001", context_rule="resolved_single_canonical",
             verification_status="VERIFIED", source="T", alias_status="ACTIVE", original_asset_id="A_X", original_alias_scope="MUNICIPALITY",
             created_at="x", updated_at="x")])
    w(base / "diagnostic_selector_v1_0_1_formal_slots_common_v1_0_1_apa_mapping_v1_0_1.csv", SLOT, [
        slot("MUNI_900001", "甲町", 1, "A_X", "甲寺", "E_X"), slot("MUNI_900001", "甲町", 2, "A_Y", "甲山", "E_Y"), slot("MUNI_900001", "甲町", 3),
        slot("MUNI_900002", "乙町", 1, "A_W", "乙町城", "E_W"), slot("MUNI_900002", "乙町", 2, "A_NA", "NA", "E_NA"), slot("MUNI_900002", "乙町", 3)])
    (tmp_path / "names.csv").write_text("candidate_name\n乙寺\n甲寺\n甲山\n", encoding="utf-8")
    return tmp_path


def spec(env, rows, name="spec.csv"):
    full = []
    for r in rows:
        d = dict.fromkeys(SPEC, "")
        d.update(municipality_id="MUNI_900001", audit_ref="AUD", president_confirmation_ref="PRES")
        d.update(r)
        full.append(d)
    p = env / name
    w(p, SPEC, full)
    return p


def run(env, sp, stage="stage", version="1.0.2", now="2026-11-20T10:00:00"):
    return subprocess.run([sys.executable, "-I", "-X", "utf8", str(SCRIPT), "--baseline-root", str(env / "base"), "--spec-file", str(sp),
                           "--measured-names", str(env / "names.csv"), "--stage-root", str(env / stage), "--version", version, "--now", now],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def rows(p):
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def slots_of(env, stage="stage", mun="MUNI_900001"):
    p = next((env / stage).glob("diagnostic_selector_*_stage.csv"))
    return [r for r in rows(p) if r["municipality_id"] == mun]


def val(env, stage="stage"):
    return json.loads((env / stage / "validation.json").read_text(encoding="utf-8"))


RELFIX = dict(op="RELFIX", asset_id="A_Z", address_original="甲町乙", address_municipality="甲町",
              official_evidence_url="https://example.go.jp/z", evidence_kind="APA_REASON")


def test_relfix_slot_clear_pass(env):
    sp = spec(env, [RELFIX, dict(op="SLOT", asset_id="A_Z", slot="1", source_tier="APA_RESOURCE", source_record_ids="C1;C2"), dict(op="CLEAR", slot="2")])
    r = run(env, sp)
    assert r.returncode == 0, r.stdout
    s = slots_of(env)
    assert [x["common_asset_id"] for x in s] == ["A_Z", "", ""]
    assert s[1]["promotion_reason"] == "NO_ELIGIBLE_CANDIDATE" and s[1]["canonical_name"] == ""
    assert s[0]["relation_type"] == "SELF_RESOURCE"
    rel = rows(next((env / "stage").glob("common_asset_municipality_relation_*_stage.csv")))
    z = [x for x in rel if x["asset_id"] == "A_Z"]
    assert [x["relation_status"] for x in z] == ["SUPERSEDED", "ACTIVE"] and z[1]["relation_type"] == "SELF_RESOURCE"
    v = val(env)
    assert v["checks"]["changed_outside_target"] == [] and v["checks"]["changed_outside_spec"] == [] and v["checks"]["baseline_unchanged"]


def test_other_municipality_untouched_and_na_preserved(env):
    sp = spec(env, [RELFIX, dict(op="SLOT", asset_id="A_Z", slot="1", source_tier="APA_RESOURCE", source_record_ids="C1"),
                    dict(op="CLEAR", slot="2")])
    assert run(env, sp).returncode == 0
    assert slots_of(env, mun="MUNI_900002") == [r for r in rows(next((env / "base").glob("diagnostic_selector_*.csv"))) if r["municipality_id"] == "MUNI_900002"]
    m = rows(next((env / "stage").glob("common_tourism_asset_master_*_stage.csv")))
    assert [x for x in m if x["asset_id"] == "A_NA"][0]["canonical_name"] == "NA"      # H1: "NA" が空になっていない
    assert [x for x in m if x["asset_id"] == "A_W"][0]["notes"] == "NA"


def test_deterministic(env):
    sp = spec(env, [RELFIX, dict(op="SLOT", asset_id="A_Z", slot="1", source_tier="APA_RESOURCE", source_record_ids="C1"), dict(op="CLEAR", slot="2")])
    assert run(env, sp, "s1").returncode == 0 and run(env, sp, "s2").returncode == 0
    for f in sorted(p.name for p in (env / "s1").iterdir()):
        assert hashlib.sha256((env / "s1" / f).read_bytes()).digest() == hashlib.sha256((env / "s2" / f).read_bytes()).digest(), f


@pytest.mark.parametrize("field", ["address_original", "official_evidence_url", "audit_ref", "president_confirmation_ref"])
def test_pipe_in_free_text_rejected(env, field):
    bad = dict(RELFIX); bad[field] = "a|b"
    sp = spec(env, [bad, dict(op="SLOT", asset_id="A_Z", slot="1", source_tier="APA_RESOURCE", source_record_ids="C1"), dict(op="CLEAR", slot="2")])
    r = run(env, sp)
    assert r.returncode != 0


def test_clear_on_already_empty_slot_is_problem(env):
    sp = spec(env, [dict(op="SLOT", asset_id="A_X", slot="1", source_tier="APA_RESOURCE", source_record_ids="C"),
                    dict(op="SLOT", asset_id="A_Y", slot="2", source_tier="APA_RESOURCE", source_record_ids="C"), dict(op="CLEAR", slot="3")])
    r = run(env, sp)
    assert r.returncode == 2 and "すでに空" in r.stdout


def test_empty_slot_may_be_omitted(env):
    sp = spec(env, [dict(op="SLOT", asset_id="A_X", slot="1", source_tier="APA_RESOURCE", source_record_ids="C"),
                    dict(op="SLOT", asset_id="A_Y", slot="2", source_tier="APA_RESOURCE", source_record_ids="C")])
    assert run(env, sp).returncode == 0


def test_filled_slot_not_specified_is_problem(env):
    sp = spec(env, [dict(op="SLOT", asset_id="A_X", slot="1", source_tier="APA_RESOURCE", source_record_ids="C")])
    assert run(env, sp).returncode == 2


def test_gap_in_filled_slots_is_problem(env):
    sp = spec(env, [dict(op="CLEAR", slot="1"), dict(op="SLOT", asset_id="A_Y", slot="2", source_tier="APA_RESOURCE", source_record_ids="C")])
    assert run(env, sp).returncode == 2


def test_relfix_wrong_municipality_address(env):
    bad = dict(RELFIX, address_municipality="乙町")
    sp = spec(env, [bad, dict(op="SLOT", asset_id="A_Z", slot="1", source_tier="APA_RESOURCE", source_record_ids="C1"), dict(op="CLEAR", slot="2")])
    assert run(env, sp).returncode == 2


def test_duplicate_rename_stops(env):
    sp = spec(env, [dict(op="RENAME", asset_id="A_X", name="甲寺院"), dict(op="RENAME", asset_id="A_X", name="甲寺院2")])
    assert run(env, sp).returncode != 0


def test_rename_updates_slot_name(env):
    sp = spec(env, [dict(op="RENAME", asset_id="A_X", name="甲寺院"),
                    dict(op="SLOT", asset_id="A_X", slot="1", source_tier="APA_RESOURCE", source_record_ids="C"),
                    dict(op="SLOT", asset_id="A_Y", slot="2", source_tier="APA_RESOURCE", source_record_ids="C")])
    r = run(env, sp)
    assert r.returncode == 0, r.stdout
    assert slots_of(env)[0]["canonical_name"] == "甲寺院"


@pytest.mark.parametrize("ver,now", [("1.0", "2026-11-20T10:00:00"), ("a.b.c", "2026-11-20T10:00:00"), ("1.0.2", "not-a-date")])
def test_bad_version_or_now_creates_nothing(env, ver, now):
    sp = spec(env, [dict(op="SLOT", asset_id="A_X", slot="1", source_tier="APA_RESOURCE", source_record_ids="C"),
                    dict(op="SLOT", asset_id="A_Y", slot="2", source_tier="APA_RESOURCE", source_record_ids="C")])
    r = run(env, sp, version=ver, now=now)
    assert r.returncode == 1
    assert not (env / "stage").exists() and not (env / "stage.tmp").exists()


def test_existing_stage_refused_and_no_tmp_left(env):
    sp = spec(env, [dict(op="SLOT", asset_id="A_X", slot="1", source_tier="APA_RESOURCE", source_record_ids="C"),
                    dict(op="SLOT", asset_id="A_Y", slot="2", source_tier="APA_RESOURCE", source_record_ids="C")])
    assert run(env, sp).returncode == 0
    assert not (env / "stage.tmp").exists()
    assert run(env, sp).returncode == 1


def test_alias_must_belong_to_target_municipality(env):
    sp = spec(env, [dict(op="ALIAS", asset_id="A_W", name="別名")])
    assert run(env, sp).returncode != 0

def _set_relation_type(env, aid, rtype):
    p = env / "base" / "common_asset_municipality_relation_v1_0_1.csv"
    rs = rows(p)
    for r in rs:
        if r["asset_id"] == aid:
            r["relation_type"] = rtype
    w(p, REL, rs)


def test_relfix_broad_area_pass(env):
    """D-090（2026-11-27）: 山・川・渓谷などの BROAD_AREA も SELF_RESOURCE に訂正できる。"""
    _set_relation_type(env, "A_Z", "BROAD_AREA")
    sp = spec(env, [RELFIX, dict(op="SLOT", asset_id="A_Z", slot="1", source_tier="APA_RESOURCE", source_record_ids="C1"), dict(op="CLEAR", slot="2")])
    r = run(env, sp)
    assert r.returncode == 0, r.stdout
    rel = rows(next((env / "stage").glob("common_asset_municipality_relation_*_stage.csv")))
    z = [x for x in rel if x["asset_id"] == "A_Z"]
    assert [x["relation_status"] for x in z] == ["SUPERSEDED", "ACTIVE"] and z[1]["relation_type"] == "SELF_RESOURCE"
    assert z[0]["relation_type"] == "BROAD_AREA"


def test_relfix_other_relation_type_rejected(env):
    _set_relation_type(env, "A_Z", "MULTI_MUNICIPALITY")
    sp = spec(env, [RELFIX, dict(op="SLOT", asset_id="A_Z", slot="1", source_tier="APA_RESOURCE", source_record_ids="C1"), dict(op="CLEAR", slot="2")])
    r = run(env, sp)
    assert r.returncode != 0
    assert "REGIONAL_CONTEXT / BROAD_AREA 以外" in r.stdout
