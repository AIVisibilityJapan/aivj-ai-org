"""費用・実行ログの集計（STEP 2 / 2-8）。タスクの記録から、日別・役割別・案件別に集計する。読み取り専用。

- 費用はドル建てで記録する。円は表示専用の目安（設定/budgets.yaml の display.usd_jpy）。上限の判定には使わない。
- 為替が未設定・不正なら、円は出さない（ドルのみ）。
- 日別は、費用が記録された時刻（履歴の cost イベント）の日付（日本時間）で集計する。
標準ライブラリのみ（為替の読み込みだけ PyYAML。無ければ円は出さない）。
"""
from __future__ import annotations

import csv
import datetime
import io
from pathlib import Path

JST = datetime.timezone(datetime.timedelta(hours=9))


def load_rate(budgets_path) -> tuple[float | None, str]:
    """(為替, 基準日)。読めない・不正な値は (None, '')。"""
    try:
        import yaml
        with open(budgets_path, encoding="utf-8") as f:
            d = (yaml.safe_load(f) or {}).get("display") or {}
        r = d.get("usd_jpy")
        if isinstance(r, bool) or not isinstance(r, (int, float)) or r <= 0:
            return None, ""
        return float(r), str(d.get("usd_jpy_as_of", ""))
    except Exception:
        return None, ""


def fmt_money(usd: float, rate: float | None) -> str:
    s = f"${usd:,.2f}" if round(usd, 2) == round(usd, 6) else f"${usd:,.4f}".rstrip("0")
    if rate is None:
        return s
    return f"{s}（約 {round(usd * rate):,} 円）"


def _project(key) -> str:
    key = str(key or "")
    return key.split(".", 1)[0] if "." in key else "（案件なし）"


def cost_events(t: dict):
    """タスクの費用イベント [(時刻, USD)]。履歴の cost イベントから。"""
    out = []
    for h in t.get("history") or []:
        if isinstance(h, dict) and h.get("event") == "cost":
            try:
                out.append((float(h["at"]), float(str(h.get("detail", "")).split()[0])))
            except (KeyError, ValueError, IndexError):
                continue
    return out


def summarize(tasks: list) -> dict:
    by_day: dict = {}
    by_role: dict = {}
    by_project: dict = {}
    for t in tasks:
        total = t.get("cost_usd", 0.0)
        if not isinstance(total, (int, float)) or isinstance(total, bool):
            continue
        by_role[t.get("role_id", "")] = by_role.get(t.get("role_id", ""), 0.0) + total
        by_project[_project(t.get("idempotency_key"))] = by_project.get(_project(t.get("idempotency_key")), 0.0) + total
        for at, usd in cost_events(t):
            day = datetime.datetime.fromtimestamp(at, JST).strftime("%Y-%m-%d")
            by_day[day] = by_day.get(day, 0.0) + usd
    r = lambda m: {k: round(v, 6) for k, v in m.items()}  # noqa: E731
    return {"total": round(sum(by_role.values()), 6), "by_day": r(by_day), "by_role": r(by_role), "by_project": r(by_project)}


def to_csv(summary: dict, rate: float | None) -> str:
    """費用集計の CSV（Excel で開けるよう BOM 付きで書く側が扱う）。"""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["区分", "キー", "費用（USD）", "円換算（目安）"])
    for kind, m in (("日別", summary["by_day"]), ("役割別", summary["by_role"]), ("案件別", summary["by_project"])):
        for k in sorted(m):
            w.writerow([kind, k, m[k], round(m[k] * rate) if rate else ""])
    w.writerow(["合計", "", summary["total"], round(summary["total"] * rate) if rate else ""])
    return buf.getvalue()


def write_csv(summary: dict, rate, out: Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        f.write(to_csv(summary, rate))
    tmp.replace(out)
    return out
