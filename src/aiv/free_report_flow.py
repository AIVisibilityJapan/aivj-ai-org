"""無償診断レポートの業務フロー（STEP 4 試験）。AI COO の task_engine に、5 つの工程の処理（handler）を登録して使う。

案件登録（自治体指定）→ 整理（AI-03-01）→ 診断メモ（AI-04-01）→ 差し込み（AI-03-05）→ 独立監査（AI-06-06）→ 社長の最終確認（承認待ちで止まる）。
- 役割は試験用の『実装済み』として渡す（台帳の impl_status は承認まで変えない）。
- 監査は作成側の出力を受け取らず、差し込み結果のファイルと根拠データだけから検査する（T4-06）。
- 監査が不合格なら、その工程が失敗し、人間キューに載る。社長の確認工程は走らない。
- 費用は常に 0（API・有料サービスなし）。外部送信はしない。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import diagnosis_memo as dm
import report_audit as ra
import report_filler as rf
import values_reader as vr

WORKFLOWS = {
    "aiv-free-report": {
        "description": "無償診断レポート（FMT v2.22・2 枚）。社長の最終確認で止まる",
        "steps": [
            {"id": "analyze", "role": "AI-03-01", "risk": "low"},
            {"id": "diagnose", "role": "AI-04-01", "risk": "low", "depends_on": ["analyze"]},
            {"id": "write", "role": "AI-03-05", "risk": "low", "depends_on": ["diagnose"]},
            {"id": "audit", "role": "AI-06-06", "risk": "low", "depends_on": ["write"]},
            {"id": "president_review", "role": "AI-000", "risk": "high", "depends_on": ["audit"],
             "action": "無償診断レポートの最終確認（外部への送付は別手順）"},
        ],
    }
}


@dataclass(frozen=True)
class TrialRole:
    role_id: str
    dept_code: str = "TRIAL"
    impl_status: str = "implemented"   # 試験用。台帳（AI_ROLES.csv）は変えない


TRIAL_ROLES = {r: TrialRole(r) for r in ("AI-000", "AI-03-01", "AI-04-01", "AI-03-05", "AI-06-06")}


class AuditRejected(Exception):
    pass


def _sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_handlers(cfg: dict) -> dict:
    """cfg: values_path, template_path, out_dir, params{issue_date,next_issue_date}, overrides, pins(任意), profile(任意), audit_fn(任意)"""
    pins = cfg.get("pins")
    audit_fn = cfg.get("audit_fn") or ra.audit

    def only(up):
        return next(iter(up.values()))

    def analyze(payload, up):
        records, src = vr.load_values(cfg["values_path"], pins)
        rec = vr.get_municipality(records, payload.get("municipality"), payload.get("municipality_id"))
        return {"org": vr.organize(rec, src, pins)}, 0.0

    def diagnose(payload, up):
        org = only(up)["org"]
        return {"memo": dm.make_memo(org)}, 0.0

    def write(payload, up):
        # 診断メモは参照のみ（差し込みは整理済みの値から。メモの文は成果物に入れない）
        records, src = vr.load_values(cfg["values_path"], pins)
        org = vr.organize(vr.get_municipality(records, payload.get("municipality"), payload.get("municipality_id")), src, pins)
        out = Path(cfg["out_dir"]) / f"{payload['municipality']}_無償診断レポート.pptx"
        Path(cfg["out_dir"]).mkdir(parents=True, exist_ok=True)
        r = rf.fill(cfg["template_path"], org, cfg["params"], out, overrides=cfg.get("overrides"))
        return {"pptx": str(out), "pptx_sha256": _sha(out), "tokens_used": r["tokens_used"]}, 0.0

    def audit(payload, up):
        w = only(up)  # 差し込み結果（ファイルの場所と SHA）だけを受け取る
        if _sha(w["pptx"]) != w["pptx_sha256"]:
            raise AuditRejected("成果物が差し込み後に変わっている（SHA 不一致）")
        records, _ = vr.load_values(cfg["values_path"], pins)          # 根拠は作成側と別に、原本から読み直す
        rec = vr.get_municipality(records, payload.get("municipality"), payload.get("municipality_id"))
        res = audit_fn(ra.extract_pptx(w["pptx"]), rec, cfg.get("profile")) if cfg.get("profile") else audit_fn(ra.extract_pptx(w["pptx"]), rec)
        if res["verdict"] == "不合格":
            top = "; ".join(f"[{x['severity']}]{x['check']}: {x['message']}" for x in res["findings"] if x["severity"] in ra.SEV_FAIL)
            raise AuditRejected(f"監査 不合格（差戻し）: {top}")
        return {"verdict": res["verdict"], "findings": res["findings"], "not_judged": res["not_judged"],
                "pptx": w["pptx"], "pptx_sha256": w["pptx_sha256"]}, 0.0

    def president_review(payload, up):
        a = only(up)
        if a["verdict"] == "不合格":
            raise AuditRejected("不合格の成果物は確認工程に進めない")
        return {"status": "社長の最終確認済み（外部への送付はしていない）", "pptx": a["pptx"]}, 0.0

    return {"AI-03-01": analyze, "AI-04-01": diagnose, "AI-03-05": write, "AI-06-06": audit, "AI-000": president_review}
