#!/usr/bin/env python3
"""Gate 判定表の更新案を stage に作る（正式 Gate は変更しない）。

入力: ベース判定表CSV、aiv_gate_ledger_check.py の ledger_check.csv、解除指定CSV
  解除指定CSV列: municipality_id, decision_reason, evidence_ref, president_confirmation_ref
出力(stage): gate_municipality_status_stage.csv / expected_diff.csv / validation.json
変更するのは、ledger_check が release_candidate=YES かつ現行がブロックの自治体の行のみ。
変更セル: unreviewed_concrete_candidate→0, preflight_result→RESOURCE_PREFLIGHT_PASS,
          decision_reason→指定値, report_generation_allowed→TRUE。他の列・他の行は不変。
gate_version / source_contract_version 列は、新版の名称が決まるまで変更しない。
"""
import argparse, csv, hashlib, json, sys
from pathlib import Path

def sha(p):
    h = hashlib.sha256(); h.update(Path(p).read_bytes()); return h.hexdigest()
def rd(p):
    with Path(p).open(encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f); return list(r.fieldnames or []), list(r)
def norm(x):
    x = (x or "").strip(); return x if x.startswith("MUNI_") else "MUNI_" + x

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-status", required=True, type=Path)
    ap.add_argument("--ledger-check", required=True, type=Path)
    ap.add_argument("--release-spec", required=True, type=Path)
    ap.add_argument("--stage-root", required=True, type=Path)
    a = ap.parse_args()
    if a.stage_root.exists(): print("stage-root が既に存在します", file=sys.stderr); return 2
    cols, base = rd(a.base_status)
    _, chk = rd(a.ledger_check); _, spec = rd(a.release_spec)
    ok = {norm(r["municipality_id"]) for r in chk if r["release_candidate"] == "YES"}
    errors = []
    targets = {}
    for s in spec:
        m = norm(s["municipality_id"])
        for k in ("decision_reason", "evidence_ref", "president_confirmation_ref"):
            if not s.get(k, "").strip(): errors.append(f"{m}: {k} が空")
        if m not in ok: errors.append(f"{m}: ledger_check で解除可になっていない")
        if m in targets: errors.append(f"{m}: 解除指定が重複")
        targets[m] = s
    by = {r["municipality_id"]: r for r in base}
    for m in targets:
        if m not in by: errors.append(f"{m}: 判定表に存在しない")
        elif by[m]["preflight_result"] != "REPORT_RESOURCE_PREFLIGHT_BLOCKED": errors.append(f"{m}: 現行がブロックではない")
    if errors:
        for e in errors: print("ERROR", e, file=sys.stderr)
        return 3
    out, diff = [], []
    for r in base:
        n = dict(r)
        if r["municipality_id"] in targets:
            s = targets[r["municipality_id"]]
            new = {"unreviewed_concrete_candidate": "0", "preflight_result": "RESOURCE_PREFLIGHT_PASS",
                   "decision_reason": s["decision_reason"].strip(), "report_generation_allowed": "TRUE"}
            for k, v in new.items():
                if n[k] != v: diff.append({"municipality_id": n["municipality_id"], "municipality_name": n["municipality_name"],
                                           "column": k, "before": n[k], "after": v,
                                           "evidence_ref": s["evidence_ref"], "president_confirmation_ref": s["president_confirmation_ref"]})
                n[k] = v
        out.append(n)
    # 自己検証
    changed_rows = {d["municipality_id"] for d in diff}
    unexpected = [(b["municipality_id"], k) for b, n in zip(base, out) for k in cols if b[k] != n[k]
                  and (b["municipality_id"] not in targets or k not in
                       ("unreviewed_concrete_candidate", "preflight_result", "decision_reason", "report_generation_allowed"))]
    assert len(out) == len(base) and not unexpected, unexpected
    a.stage_root.mkdir(parents=True)
    sp = a.stage_root / "gate_municipality_status_stage.csv"
    with sp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n"); w.writeheader(); w.writerows(out)
    with (a.stage_root / "expected_diff.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(diff[0].keys())); w.writeheader(); w.writerows(diff)
    (a.stage_root / "validation.json").write_text(json.dumps({
        "formal_gate_modified": False, "base_sha256": sha(a.base_status), "stage_sha256": sha(sp),
        "rows": len(out), "columns_unchanged": True, "changed_municipalities": sorted(changed_rows),
        "changed_cells": len(diff), "unexpected_changes": 0,
        "note": "gate_version/source_contract_version 列は未変更。契約JSON・config・pointer・アダプタは新版名決定後に別途作成。"},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print("OK", sorted(changed_rows), "cells:", len(diff)); return 0

if __name__ == "__main__":
    sys.exit(main())
