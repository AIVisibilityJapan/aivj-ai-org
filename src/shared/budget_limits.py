"""設定/budgets.yaml から、実行基盤が使う上限を読み込む（D-035）。標準ライブラリ＋PyYAML のみ。

未設定（null）・不正な値は、そのまま None にして返す。基盤側（task_engine / approval_queue）が
None を『起動拒否・承認拒否』として扱う（fail closed）。ここで勝手に既定値を補わない。
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent


def _num(v, integer: bool = False):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
        return None
    return int(v) if integer else v


def load(path=ROOT / "設定" / "budgets.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        d = yaml.safe_load(f) or {}
    per = d.get("per_run_limits") or {}
    daily = d.get("daily_limits") or {}
    cb = d.get("circuit_breaker") or {}
    ap = d.get("approval") or {}
    hq = d.get("human_queue") or {}
    engine = {"max_retries": _num(per.get("max_retries"), True), "max_runtime_seconds": _num(per.get("max_runtime_seconds"), True),
              "consecutive_failures_to_stop_role": _num(cb.get("consecutive_failures_to_stop_role"), True),
              "max_cost_usd": _num(per.get("max_cost_usd"))}
    approval = {"ttl_hours": _num(ap.get("ttl_hours")), "max_pending_high_risk": _num(hq.get("max_pending_high_risk"), True)}
    return {"engine": engine, "approval": approval, "daily_max_cost_usd": _num(daily.get("max_cost_usd"))}
