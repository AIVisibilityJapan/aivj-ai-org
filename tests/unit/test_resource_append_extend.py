"""追記ツール v2: 既存広域資産への所属自治体の追加（extend_municipality=1。D-092）のテスト。"""
import importlib.util, json, subprocess, sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "scripts" / "aiv_resource_append_v2.py"
SLOT_COLS = ["municipality_id", "municipality_name", "display_slot", "common_asset_id", "canonical_name", "source_tier", "source_namespace",
             "source_record_id", "appearance_candidate_rank", "apa_source_information", "dedup_reason", "promotion_reason", "resource_scope",
             "relation_type", "relation_status", "relation_evidence_id", "verification_status", "asset_status"]
MCOLS = ["asset_id", "canonical_name", "canonical_name_normalized", "resource_type", "resource_subtype", "primary_municipality_id", "verified_municipality_ids",
         "verification_status", "asset_status", "first_source", "first_source_asset_id", "first_seen_measurement", "last_verified_at", "merge_basis",
         "merge_confidence", "created_at", "updated_at", "notes"]
RCOLS = ["asset_id", "municipality_id", "relation_type", "verification_status", "is_primary", "evidence_id", "relation_status", "original_asset_id",
         "original_relation_type", "updated_at", "notes"]
ACOLS = ["asset_id", "alias", "alias_scope", "municipality_id", "context_rule", "verification_status", "source", "alias_status", "original_asset_id",
         "original_alias_scope", "created_at", "updated_at", "notes"]
SPEC = ["municipality_id", "asset_id", "measured_name", "existence_status", "address_original", "address_municipality", "official_evidence_url",
        "evidence_kind", "source_record_ids", "audit_ref", "president_confirmation_ref", "alias", "relation_type_to", "new_resource_subtype",
        "new_resource_type", "extend_municipality"]


def _w(p, rows, cols):
    pd.DataFrame(rows, columns=cols).to_csv(p, index=False, encoding="utf-8-sig")


def _base(tmp, verified="262145|263648"):
    b = tmp / "base"; b.mkdir()
    m = {c: "" for c in MCOLS}
    m.update(asset_id="A_RIVER", canonical_name="木津川", canonical_name_normalized="木津川", primary_municipality_id="262145",
             verified_municipality_ids=verified, verification_status="VERIFIED", asset_status="ACTIVE", notes="orig")
    m2 = dict(m, asset_id="A_OTHER", canonical_name="寺", canonical_name_normalized="寺")
    _w(b / "common_tourism_asset_master_v1_1_1.csv", [m, m2], MCOLS)
    _w(b / "common_tourism_asset_alias_v1_1_1.csv", [], ACOLS)
    _w(b / "common_asset_municipality_relation_v1_1_1.csv", [], RCOLS)
    rows = []
    for mid, nm in (("MUNI_262111", "京田辺市"), ("MUNI_262145", "木津川市")):
        for s in (1, 2, 3):
            r = {c: "" for c in SLOT_COLS}
            r.update(municipality_id=mid, municipality_name=nm, display_slot=str(s))
            rows.append(r)
    _w(b / "diagnostic_selector_v1_5_1_formal_slots_common_v1_1_1_apa_mapping_v1_1_1.csv", rows, SLOT_COLS)
    return b


def _spec(tmp, extend="1", mid="262111", muni="京田辺市"):
    r = {c: "" for c in SPEC}
    r.update(municipality_id=mid, asset_id="A_RIVER", measured_name="木津川", existence_status="確認済み", address_original="京田辺市",
             address_municipality=muni, official_evidence_url="https://example.invalid", evidence_kind="APA_REASON", source_record_ids="X1",
             audit_ref="AUD", president_confirmation_ref="REF", extend_municipality=extend)
    p = tmp / "spec.csv"; _w(p, [r], SPEC)
    meas = tmp / "meas.csv"; _w(meas, [["木津川"]], ["candidate_text"])
    return p, meas


def _run(tmp, base, spec, meas, stage="stage"):
    return subprocess.run([sys.executable, str(TOOL), "--baseline-root", str(base), "--spec-file", str(spec), "--measured-names", str(meas),
                           "--stage-root", str(tmp / stage), "--version", "1.5.2", "--now", "2026-11-27T12:00:00+09:00", "--strict"],
                          capture_output=True, text=True)


def test_extend_adds_municipality_and_fills_slot(tmp_path):
    base = _base(tmp_path); spec, meas = _spec(tmp_path)
    r = _run(tmp_path, base, spec, meas)
    assert r.returncode == 0, r.stdout + r.stderr
    st = tmp_path / "stage"
    m = pd.read_csv(next(st.glob("common_tourism_asset_master_*_stage.csv")), dtype=str).fillna("")
    row = m[m.asset_id == "A_RIVER"].iloc[0]
    assert row.verified_municipality_ids == "262145|263648|262111"
    assert "EXTENDED_MUNI=262111" in row.notes and row.notes.startswith("orig")
    assert m[m.asset_id == "A_OTHER"].iloc[0].notes == "orig"
    v = json.loads((st / "validation.json").read_text(encoding="utf-8"))
    assert v["status"] == "PASS" and v["checks"]["master_old_rows_identical"] is True


def test_without_flag_rejected(tmp_path):
    base = _base(tmp_path); spec, meas = _spec(tmp_path, extend="")
    r = _run(tmp_path, base, spec, meas)
    assert r.returncode == 1 and "extend_municipality=1" in r.stdout


def test_already_member_is_noop_for_master(tmp_path):
    base = _base(tmp_path, verified="262145|263648|262111"); spec, meas = _spec(tmp_path)
    r = _run(tmp_path, base, spec, meas)
    assert r.returncode == 0, r.stdout
    assert not list((tmp_path / "stage").glob("common_tourism_asset_master_*_stage.csv"))


def test_address_municipality_mismatch_rejected(tmp_path):
    base = _base(tmp_path); spec, meas = _spec(tmp_path, muni="木津川市")
    r = _run(tmp_path, base, spec, meas)
    assert r.returncode == 1
