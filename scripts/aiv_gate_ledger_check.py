#!/usr/bin/env python3
"""Gate 解除候補チェック（読み取り専用・stage出力のみ）。

レビュー台帳が、自治体ごとの解除条件を満たすかを機械的に判定する。
正式 Gate・pointer・判定表は一切書き換えない。
条件（自治体ごと）:
  C1 台帳に行がある
  C2 判定が「要確認」の行が 0
  C3 判定「採用」の行は existence_status が「確認済み」で始まり、address_municipality が当該自治体名
  C4 --candidates-file の全候補が台帳に載っている（名前の完全一致、または台帳名の構成語との一致）
  C5 現Gateが REPORT_RESOURCE_PREFLIGHT_BLOCKED（既に通過の自治体は対象外）
"""
from __future__ import annotations
import argparse, csv, json, re, sys, unicodedata
from pathlib import Path

JUDGMENTS = {"採用", "不採用", "今回不使用", "要確認"}
REQUIRED = ["municipality_id", "candidate_name", "existence_status", "address_municipality", "judgment", "audit_ref"]

def nk(s):
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"[（(][^）)]*[）)]", "", s)  # 括弧内の補足は無視
    return re.sub(r"[\s・･·\-‐－―]", "", s)

def tokens(name):
    # 「A/B」「A(B)」を構成語に分解
    out = set()
    for part in re.split(r"[/／]", name):
        out.add(nk(part))
        for m in re.findall(r"[（(]([^）)]*)[）)]", unicodedata.normalize("NFKC", part)):
            out.add(nk(m))
    return {t for t in out if t}

def mid_norm(x):
    x = (x or "").strip()
    return x if x.startswith("MUNI_") or not x or x == "*" else "MUNI_" + x

def rd(p):
    with Path(p).open(encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f); return list(r.fieldnames or []), list(r)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True, type=Path)
    ap.add_argument("--gate-status", required=True, type=Path)
    ap.add_argument("--candidates-file", type=Path, help="測定由来の抽出候補（candidate_name 列）。municipality_id 列があれば自治体別")
    ap.add_argument("--stage-root", required=True, type=Path)
    a = ap.parse_args()
    if a.stage_root.exists():
        print("stage-root が既に存在します", file=sys.stderr); return 2
    lf, ledger = rd(a.ledger)
    miss = [c for c in REQUIRED if c not in lf]
    if miss:
        print("台帳の必須列がありません:", miss, file=sys.stderr); return 2
    gf, gate = rd(a.gate_status)
    gate_by = {r["municipality_id"]: r for r in gate}
    cands = {}
    if a.candidates_file:
        cf, cr = rd(a.candidates_file)
        for r in cr:
            cands.setdefault(mid_norm(r.get("municipality_id")) or "*", []).append(r["candidate_name"])
    by_m = {}
    for r in ledger: by_m.setdefault(mid_norm(r["municipality_id"]), []).append(r)
    results, problems = [], []
    for mid, rows in sorted(by_m.items()):
        g = gate_by.get(mid)
        reasons = []
        if g is None: reasons.append("C1:Gate表に自治体なし")
        else:
            mname = g["municipality_name"]
            if g["preflight_result"] != "REPORT_RESOURCE_PREFLIGHT_BLOCKED": reasons.append("C5:既にブロックではない")
            for r in rows:
                if r["judgment"] not in JUDGMENTS: reasons.append(f"C2:不正な判定[{r['candidate_name']}]={r['judgment']}")
            pend = [r["candidate_name"] for r in rows if r["judgment"] == "要確認"]
            if pend: reasons.append("C2:要確認あり[" + " / ".join(pend) + "]")
            for r in rows:
                if r["judgment"] == "採用":
                    if not r["existence_status"].startswith("確認済み"): reasons.append(f"C3:実在未確認[{r['candidate_name']}]")
                    if r["address_municipality"] != mname: reasons.append(f"C3:所在自治体不一致[{r['candidate_name']}]={r['address_municipality']}")
            led_tokens = set()
            for r in rows: led_tokens |= tokens(r["candidate_name"])
            exp = cands.get(mid, cands.get("*", []))
            if a.candidates_file:
                for c in exp:
                    n = nk(c)
                    if not any(n == t or n in t for t in led_tokens): reasons.append(f"C4:台帳に無い候補[{c}]")
        results.append({"municipality_id": mid, "municipality_name": g["municipality_name"] if g else "",
                        "ledger_rows": len(rows), "adopted": sum(r["judgment"] == "採用" for r in rows),
                        "release_candidate": "YES" if not reasons else "NO", "reasons": " | ".join(reasons)})
    a.stage_root.mkdir(parents=True)
    with (a.stage_root / "ledger_check.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys())); w.writeheader(); w.writerows(results)
    (a.stage_root / "validation.json").write_text(json.dumps({
        "formal_gate_modified": False, "municipalities": len(results),
        "release_candidates": [r["municipality_id"] for r in results if r["release_candidate"] == "YES"],
        "blocked": {r["municipality_id"]: r["reasons"] for r in results if r["release_candidate"] == "NO"}},
        ensure_ascii=False, indent=2), encoding="utf-8")
    for r in results: print(r["municipality_id"], r["municipality_name"], r["release_candidate"], r["reasons"])
    return 0

if __name__ == "__main__":
    sys.exit(main())
