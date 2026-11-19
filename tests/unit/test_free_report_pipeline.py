"""aiv_free_report_pipeline.py の試験。既存ツールは「見せかけの部品（スタブ）」に差し替えて、
段階の順序・止まる条件・承認番号の検査・出力の一致確認を確かめる（実データには触れない）。"""
import csv, importlib.util, json, sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "scripts" / "aiv_free_report_pipeline.py"
spec = importlib.util.spec_from_file_location("pipe", SRC)
pipe = importlib.util.module_from_spec(spec); spec.loader.exec_module(pipe)

STUB_EXTRACT = r'''
import sys, json, argparse
from pathlib import Path
ap = argparse.ArgumentParser(); ap.add_argument("--formal-root"); ap.add_argument("--show-resolved", action="store_true")
ap.add_argument("name", nargs="?"); ap.add_argument("pref", nargs="?"); a = ap.parse_args()
cfg = json.loads(Path(a.formal_root).joinpath("cfg.json").read_text(encoding="utf-8"))
if a.show_resolved:
    print(json.dumps({"versions": cfg["versions"], "files": cfg["files"]}, ensure_ascii=False)); sys.exit(0)
out = Path(cfg["work"]) / "出力" / f"候補抽出_{a.name}_20261120_000000"; out.mkdir(parents=True); (out / "01.csv").write_text("x", encoding="utf-8")
'''
STUB_LEDGER = r'''
import sys, csv, argparse
from pathlib import Path
ap = argparse.ArgumentParser(); [ap.add_argument("--" + k) for k in ("ledger", "gate-status", "candidates-file", "stage-root")]; a = ap.parse_args()
root = Path(a.stage_root); root.mkdir(parents=True)
rows = list(csv.DictReader(open(a.ledger, encoding="utf-8-sig")))
ids = sorted({r["municipality_id"] for r in rows})
with open(root / "ledger_check.csv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f); w.writerow(["municipality_id", "municipality_name", "ledger_rows", "adopted", "release_candidate", "reasons"])
    for i in ids:
        blocked = i.endswith("2")  # 末尾 2 は「すでに通過」の扱い
        w.writerow([i, "n", 1, 1, "NO" if blocked else "YES", "C5:既にブロックではない" if blocked else ""])
'''
STUB_APPEND = r'''
import sys, csv, json, argparse
from pathlib import Path
ap = argparse.ArgumentParser()
for k in ("baseline-root", "spec-file", "stage-root", "version", "now"): ap.add_argument("--" + k)
ap.add_argument("--measured-names", nargs="*"); ap.add_argument("--strict", action="store_true"); a = ap.parse_args()
root = Path(a.stage_root); root.mkdir(parents=True)
rows = list(csv.DictReader(open(a.spec_file, encoding="utf-8-sig")))
munis = sorted({r["municipality_id"] for r in rows})
import os
bad = os.environ.get("STUB_BAD")
v = {"status": "PASS", "checks": {"changed_outside_spec": ["X"] if bad == "outside" else [], "changed_municipalities": munis, "new_assets": 0, "baseline_unchanged": True}}
(root / "validation.json").write_text(json.dumps(v), encoding="utf-8")
extra = str(os.getpid()) if bad == "nondeterministic" else "same"
(root / "expected_diff.csv").write_text("file,municipality_id,asset_id,field,before,after,note\nslot,%s,A,display_slot=1:canonical_name,,資源,%s\n" % (munis[0], extra), encoding="utf-8")
print(json.dumps({"status": "PASS"}))
'''


def build_env(tmp_path, ledger_judgment="採用", gate_pass_ids=()):
    root = tmp_path / "repo"; (root / "scripts").mkdir(parents=True)
    for name, body in (("aiv_extract_candidates_one_v3.py", STUB_EXTRACT), ("aiv_gate_ledger_check.py", STUB_LEDGER), ("aiv_resource_append_v2.py", STUB_APPEND)):
        (root / "scripts" / name).write_text(body, encoding="utf-8")
    fr = root / "formal"; fr.mkdir()
    files = {}
    for k in ("selector", "master", "alias", "relation", "gate"):
        p = fr / f"{k}.csv"; p.write_text(k + "\n", encoding="utf-8"); files[k] = str(p)
    (fr / "gate.csv").write_text("municipality_id,municipality_name,prefecture,preflight_result,unreviewed_concrete_candidate\nMUNI_100001,甲市,京都府,REPORT_RESOURCE_PREFLIGHT_BLOCKED,2\n", encoding="utf-8")
    work = root / "データ/private/06-STEP4作業/資源確認"
    (fr / "cfg.json").write_text(json.dumps({"versions": {"selector": "1.5.56"}, "files": files, "work": str(work)}), encoding="utf-8")
    d = work / "追記指定"; d.mkdir(parents=True)
    led = ["municipality_id,candidate_name,judgment\n", f"MUNI_100001,資源A,{ledger_judgment}\n", "MUNI_100002,資源B,不採用\n"]
    (d / "テスト_レビュー台帳.csv").write_text("".join(led), encoding="utf-8-sig")
    (d / "テスト_抽出候補.csv").write_text("municipality_id,candidate_name\nMUNI_100001,資源A\n", encoding="utf-8-sig")
    (d / "テスト_追記指定.csv").write_text("municipality_id,asset_id,president_confirmation_ref\nMUNI_100001,NEW,2026第1回3Q-100001-20261120\n", encoding="utf-8-sig")
    (d / "テスト_測定固有名詞.csv").write_text("candidate_text\n資源A\n", encoding="utf-8-sig")
    return root, fr


def run(root, fr, *args):
    return pipe.main(["--repo-root", str(root), "--formal-root", str(fr)] + list(args))


def prepared(tmp_path, **kw):
    root, fr = build_env(tmp_path, **kw)
    assert run(root, fr, "prepare", "--run-name", "テスト", "--muni", "甲市:京都府") == 0
    rid = next(p.name for p in (root / "データ/private/06-STEP4作業/資源確認/一括").iterdir())
    return root, fr, rid


# ---- 部品 ----
def test_bump_and_refs():
    assert pipe.bump_patch("1.5.56") == "1.5.57"
    assert pipe.valid_ref("2026第1回3Q-262048-20261120") and pipe.valid_ref("2026第1回3Q-262048-20261120-3")
    for bad in ("", None, "026第1回3Q-262048-20261120", "2026第1回3Q-26204-20261120", "PRES1-262048-20261114"):
        assert not pipe.valid_ref(bad)
    assert pipe.mid_norm("262048") == "MUNI_262048" and pipe.mid_norm("MUNI_1") == "MUNI_1"


def test_first_free_and_no_overwrite(tmp_path):
    p = tmp_path / "x"; p.mkdir()
    assert pipe.first_free(p) == Path(f"{p}_try2")
    f = tmp_path / "f.csv"; pipe.wr(f, ["a"], [["1"]])
    with pytest.raises(pipe.Stop):
        pipe.wr(f, ["a"], [["1"]])


# ---- 段階 ----
def test_prepare_then_stage_ok(tmp_path):
    root, fr, rid = prepared(tmp_path)
    assert run(root, fr, "stage", "--run", rid) == 0
    st = json.loads((root / f"データ/private/06-STEP4作業/資源確認/一括/{rid}/state.json").read_text(encoding="utf-8"))
    assert st["phase"] == "stage_done" and st["gate_targets"] == ["MUNI_100001"] and st["append_version"] == "1.5.57"
    summ = (root / f"データ/private/一時保存/一括_{rid}/要約_stage.md").read_text(encoding="utf-8")
    assert "Gate がすでに通過" in summ and "資源" in summ


def test_stage_stops_on_pending_ledger(tmp_path):
    root, fr, rid = prepared(tmp_path, ledger_judgment="保留")
    assert run(root, fr, "stage", "--run", rid) == 3
    assert "保留" in (root / f"データ/private/一時保存/一括_{rid}/要約_stage.md").read_text(encoding="utf-8")


def test_stage_stops_when_version_changed(tmp_path):
    root, fr, rid = prepared(tmp_path)
    cfg = json.loads((fr / "cfg.json").read_text(encoding="utf-8")); cfg["versions"]["selector"] = "1.5.57"
    (fr / "cfg.json").write_text(json.dumps(cfg), encoding="utf-8")
    assert run(root, fr, "stage", "--run", rid) == 3


def test_stage_stops_on_changed_file_sha(tmp_path):
    root, fr, rid = prepared(tmp_path)
    (fr / "selector.csv").write_text("changed\n", encoding="utf-8")
    assert run(root, fr, "stage", "--run", rid) == 3


def test_stage_stops_on_outside_spec(tmp_path, monkeypatch):
    root, fr, rid = prepared(tmp_path)
    monkeypatch.setenv("STUB_BAD", "outside")
    assert run(root, fr, "stage", "--run", rid) == 3


def test_stage_stops_when_two_runs_differ(tmp_path, monkeypatch):
    root, fr, rid = prepared(tmp_path)
    monkeypatch.setenv("STUB_BAD", "nondeterministic")
    # 2 回の実行でプロセス ID が違うので出力が一致しない
    assert run(root, fr, "stage", "--run", rid) == 3


def test_phase_order_enforced(tmp_path):
    root, fr, rid = prepared(tmp_path)
    assert run(root, fr, "approve1", "--run", rid) == 3   # stage 前
    assert run(root, fr, "approve2", "--run", rid) == 3


def test_approve1_requires_valid_refs(tmp_path):
    root, fr, rid = prepared(tmp_path)
    assert run(root, fr, "stage", "--run", rid) == 0
    # 承認番号.csv なし
    assert run(root, fr, "approve1", "--run", rid) == 3
    d = root / f"データ/private/06-STEP4作業/資源確認/一括/{rid}"
    (d / "承認番号.csv").write_text("municipality_id,ref1,ref_gate,ref_switch\nMUNI_100001,bad,bad,\n", encoding="utf-8-sig")
    assert run(root, fr, "approve1", "--run", rid) == 3
    summ = (root / f"データ/private/一時保存/一括_{rid}/要約_approve1.md").read_text(encoding="utf-8")
    assert "形式が違います" in summ


def test_duplicate_run_id_refused(tmp_path):
    root, fr, rid = prepared(tmp_path)
    assert run(root, fr, "prepare", "--run-name", "テスト", "--muni", "甲市:京都府") == 3


def test_formal_files_untouched(tmp_path):
    root, fr, rid = prepared(tmp_path)
    before = pipe.tree_hashes(fr)
    run(root, fr, "stage", "--run", rid)
    assert pipe.tree_hashes(fr) == before


STUB_GATE = r"""
import argparse, csv, json
from pathlib import Path
ap = argparse.ArgumentParser()
for k in ("base-status", "ledger-check", "release-spec", "stage-root"): ap.add_argument("--" + k)
a = ap.parse_args(); r = Path(a.stage_root); r.mkdir(parents=True)
ids = [x["municipality_id"] for x in csv.DictReader(open(a.release_spec, encoding="utf-8-sig"))]
(r / "validation.json").write_text(json.dumps({"unexpected_changes": 0, "columns_unchanged": True, "changed_municipalities": ids}), encoding="utf-8")
"""
STUB_BUILD = r"""
import argparse
from pathlib import Path
ap = argparse.ArgumentParser()
for k in ("formal-root", "out", "append-stage", "gate-stage", "date"): ap.add_argument("--" + k)
a = ap.parse_args(); Path(a.out).mkdir(parents=True); print("現行版 {'sel': '1.5.56'} → 新版 {'sel': '1.5.57'}")
"""
STUB_SWITCH = r"""
import argparse, json, os
from pathlib import Path
ap = argparse.ArgumentParser(); ap.add_argument("cmd")
for k in ("formal-root", "stage", "work", "approval-ref"): ap.add_argument("--" + k)
ap.add_argument("--execute", action="store_true"); a = ap.parse_args()
if a.cmd == "validate":
    print(json.dumps({"check_on_formal": {"ready": True}, "compare": {"PASS": True, "binding_new": {"munis": {"MUNI_100001": [["資源A", "FILLED"], ["―", "EMPTY"], ["―", "EMPTY"]]}}}}))
elif a.execute:
    Path(os.environ["STUB_LOG"]).write_text(a.approval_ref, encoding="utf-8"); print(json.dumps({"switched": True, "backup": "BK"}))
else:
    print(json.dumps({"ready": True, "conflicts": []}))
"""
STUB_REPORT = r"""
import argparse, json, os
from pathlib import Path
from pptx import Presentation
ap = argparse.ArgumentParser(); ap.add_argument("--formal-root"); ap.add_argument("--tag"); ap.add_argument("--ids", nargs="*"); a = ap.parse_args()
base = Path(os.environ["STUB_REPORT_DIR"]); (base / "PowerPoint").mkdir(parents=True, exist_ok=True); (base / "PDF").mkdir(exist_ok=True)
for i in a.ids:
    n = "甲市" if i.endswith("1") else "乙村"
    pr = Presentation()
    for k in range(2):
        s = pr.slides.add_slide(pr.slide_layouts[5]); s.shapes.title.text = n + (" 資源A" if (k == 0 and n == "甲市") else "")
    pr.core_properties.author = ""; pr.core_properties.last_modified_by = ""
    pp = base / "PowerPoint" / f"{n}_無償診断レポート.pptx"; pr.save(str(pp))
    pdf = base / "PDF" / f"{n}_無償診断レポート.pdf"; pdf.write_bytes(b"%PDF /Type /Page\n/Type /Page\n/Type /Pages")
    print(json.dumps({"municipality": n, "out": str(pp), "pdf": str(pdf), "pdf_result": "OK", "warn": [], "values": {"assets": ["資源A", "―", "―"] if n == "甲市" else ["―", "―", "―"], "rank": 1, "rate": ["0.0%"] * 3, "grades": ["E"] * 3}}, ensure_ascii=False))
"""


def add_release_stubs(root):
    for name, body in (("aiv_gate_release_stage.py", STUB_GATE), ("aiv_release_build.py", STUB_BUILD), ("aiv_release_switch_v2.py", STUB_SWITCH), ("aiv_make_free_report.py", STUB_REPORT)):
        (root / "scripts" / name).write_text(body, encoding="utf-8")


def to_approve1(tmp_path, monkeypatch):
    root, fr, rid = prepared(tmp_path)
    add_release_stubs(root)
    monkeypatch.setenv("STUB_LOG", str(tmp_path / "switch.log")); monkeypatch.setenv("STUB_REPORT_DIR", str(tmp_path / "reports"))
    assert run(root, fr, "stage", "--run", rid) == 0
    d = root / f"データ/private/06-STEP4作業/資源確認/一括/{rid}"
    ok = "2026第1回3Q-100001-20261120"
    (d / "承認番号.csv").write_text(f"municipality_id,ref1,ref_gate,ref_switch\nMUNI_100001,{ok},{ok}-2,{ok}-3\n", encoding="utf-8-sig")
    return root, fr, rid, d


def test_approve1_ok_and_does_not_switch(tmp_path, monkeypatch):
    root, fr, rid, d = to_approve1(tmp_path, monkeypatch)
    assert run(root, fr, "approve1", "--run", rid) == 0
    assert not (tmp_path / "switch.log").exists()      # 本番の切替は呼ばれない
    summ = (root / f"データ/private/一時保存/一括_{rid}/要約_approve1.md").read_text(encoding="utf-8")
    assert "1.5.57" in summ and "資源A" in summ


def test_approve1_ref_mismatch_with_spec(tmp_path, monkeypatch):
    root, fr, rid, d = to_approve1(tmp_path, monkeypatch)
    (d / "承認番号.csv").write_text("municipality_id,ref1,ref_gate,ref_switch\nMUNI_100001,2026第1回3Q-100001-20261121,2026第1回3Q-100001-20261121-2,\n", encoding="utf-8-sig")
    assert run(root, fr, "approve1", "--run", rid) == 3
    assert "ref1 が違います" in (root / f"データ/private/一時保存/一括_{rid}/要約_approve1.md").read_text(encoding="utf-8")


def test_approve2_requires_ref_switch_and_switches_once(tmp_path, monkeypatch):
    root, fr, rid, d = to_approve1(tmp_path, monkeypatch)
    assert run(root, fr, "approve1", "--run", rid) == 0
    ok = "2026第1回3Q-100001-20261120"
    (d / "承認番号.csv").write_text(f"municipality_id,ref1,ref_gate,ref_switch\nMUNI_100001,{ok},{ok}-2,\n", encoding="utf-8-sig")
    assert run(root, fr, "approve2", "--run", rid) == 3
    assert not (tmp_path / "switch.log").exists()      # 承認番号が空なら切替しない
    (d / "承認番号.csv").write_text(f"municipality_id,ref1,ref_gate,ref_switch\nMUNI_100001,{ok},{ok}-2,{ok}-3\n", encoding="utf-8-sig")
    assert run(root, fr, "approve2", "--run", rid) == 0
    assert (tmp_path / "switch.log").read_text(encoding="utf-8") == f"{ok}-3"
    summ = (root / f"データ/private/一時保存/一括_{rid}/要約_approve2.md").read_text(encoding="utf-8")
    assert "問題なし" in summ and "BK" in summ


def test_approve2_blocks_when_formal_changed(tmp_path, monkeypatch):
    root, fr, rid, d = to_approve1(tmp_path, monkeypatch)
    assert run(root, fr, "approve1", "--run", rid) == 0
    (fr / "gate.csv").write_text("changed\n", encoding="utf-8")
    assert run(root, fr, "approve2", "--run", rid) == 3
    assert not (tmp_path / "switch.log").exists()
