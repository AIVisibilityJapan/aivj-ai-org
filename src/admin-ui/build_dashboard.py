"""管理画面（STEP 2 / 2-7）。実行状態を読み取り、1 枚の HTML を作る。表示専用。

- 読むだけ。実行状態は変更しない（承認・停止・再開はここでは行わない。D-027 の回答: 画面は表示のみ）。
- 外部へは何も送らない。HTML に script・外部読み込み・リンクを入れない（CSP でも禁止）。
- 依頼の中身（payload）・実行結果（result）・人間キューの詳細は表示しない。
- 読めないファイルは「読めない」と明示して表示する（見えないまま隠さない）。
- 上限値が未設定の項目は「未設定（起動しない）」と表示する（fail closed の見える化）。
使い方（リポジトリのルートで）: python src/admin-ui/build_dashboard.py  → データ/実行状態/管理画面.html
標準ライブラリのみ。
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src" / "shared"))
import cost_report as cr  # noqa: E402
DEFAULT_STATE = ROOT / "データ" / "実行状態"
BUDGETS = ROOT / "設定" / "budgets.yaml"
ACTIVE = {"queued", "running", "awaiting_approval"}
LABEL = {"queued": "待機", "running": "実行中", "succeeded": "成功", "failed": "失敗", "stopped": "停止",
         "awaiting_approval": "承認待ち", "blocked": "ブロック", "rejected": "差戻し"}


def _esc(v) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def _ts(v) -> str:
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return ""
    return datetime.datetime.fromtimestamp(v).strftime("%m-%d %H:%M")


def _load_dir(d: Path, problems: list) -> list:
    out = []
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                x = json.load(f)
            if not isinstance(x, dict):
                raise ValueError("形式が不正")
            out.append(x)
        except (OSError, ValueError) as e:
            problems.append(f"{d.name}/{p.name}: 読めません（{type(e).__name__}）")
    return out


def _load_jsonl(p: Path, problems: list) -> list:
    out = []
    if not p.exists():
        return out
    try:
        with open(p, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    x = json.loads(line)
                    if isinstance(x, dict):
                        out.append(x)
                        continue
                except ValueError:
                    pass
                problems.append(f"{p.name}: {n} 行目が読めません")
    except OSError as e:
        problems.append(f"{p.name}: 読めません（{type(e).__name__}）")
    return out


def _load_json(p: Path, default, problems: list):
    if not p.exists():
        return default
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        problems.append(f"{p.name}: 読めません（{type(e).__name__}）")
        return default


def _limits_view(budgets_path: Path) -> list:
    """上限値の設定状況。値は budgets.yaml から。読めなければ全て『不明』。"""
    names = [("per_run_limits", "max_cost_usd", "1 回の費用上限"), ("per_run_limits", "max_runtime_seconds", "1 回の実行時間上限"),
             ("per_run_limits", "max_retries", "再試行の上限"), ("daily_limits", "max_cost_usd", "1 日の費用上限"),
             ("circuit_breaker", "consecutive_failures_to_stop_role", "連続失敗での自動停止"),
             ("approval", "ttl_hours", "承認の有効期限（時間）"), ("human_queue", "max_pending_high_risk", "高リスク作業の滞留上限")]
    try:
        import yaml
        with open(budgets_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return [(label, None, "不明") for _, _, label in names]
    out = []
    for sec, key, label in names:
        v = (data.get(sec) or {}).get(key)
        out.append((label, v, "未設定（起動しない）" if v is None else str(v)))
    return out


def collect(state_dir, budgets_path=BUDGETS, now: float | None = None) -> dict:
    s = Path(state_dir)
    problems: list = []
    now = time.time() if now is None else now
    tasks = _load_dir(s / "tasks", problems)
    approvals = _load_dir(s / "approvals", problems)
    items = _load_dir(s / "human_queue", problems)
    stopped = _load_json(s / "停止.json", [], problems)
    streak = _load_json(s / "連続失敗.json", {}, problems)
    stop_log = _load_jsonl(s / "停止ログ.jsonl", problems)
    appr_log = _load_jsonl(s / "承認記録.jsonl", problems)
    notify = _load_jsonl(s / "通知送信待ち.jsonl", problems)
    projects: dict = {}
    for t in tasks:
        key = str(t.get("idempotency_key", ""))
        pid = key.split(".", 1)[0] if "." in key else "（案件なし）"
        projects.setdefault(pid, []).append(t)
    cost = round(sum(t.get("cost_usd", 0.0) for t in tasks if isinstance(t.get("cost_usd", 0.0), (int, float))), 6)
    open_items = [i for i in items if i.get("status") == "open"]
    return {"now": now, "problems": problems, "tasks": tasks, "projects": projects, "approvals": approvals,
            "pending": [a for a in approvals if a.get("status") == "pending"], "items": open_items,
            "overdue": [i for i in open_items if isinstance(i.get("due"), (int, float)) and i["due"] < now],
            "stopped": sorted(str(x) for x in stopped) if isinstance(stopped, list) else [],
            "streak": streak if isinstance(streak, dict) else {}, "stop_log": stop_log, "appr_log": appr_log,
            "notify_unsent": [n for n in notify if not n.get("sent")], "cost": cost,
            "limits": _limits_view(Path(budgets_path)),
            "rate": cr.load_rate(budgets_path), "costs": cr.summarize(tasks)}


def _task_reason(t: dict) -> str:
    h = t.get("history") or []
    return str(h[-1].get("detail", "")) if h and isinstance(h[-1], dict) else ""


def _table(head: list, rows: list) -> str:
    if not rows:
        return '<p class="muted">なし</p>'
    th = "".join(f"<th>{_esc(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


def render(d: dict) -> str:
    n = {k: sum(1 for t in d["tasks"] if t.get("status") == k) for k in LABEL}
    tiles = [("停止中", len(d["stopped"]), bool(d["stopped"])), ("承認待ち", len(d["pending"]), bool(d["pending"])),
             ("未対応（人）", len(d["items"]), False), ("期限超過", len(d["overdue"]), bool(d["overdue"])),
             ("失敗", n["failed"], n["failed"] > 0), ("差戻し", n["rejected"], n["rejected"] > 0), ("ブロック", n["blocked"], n["blocked"] > 0),
             ("実行中・待機", n["running"] + n["queued"], False), ("費用合計", cr.fmt_money(d["cost"], d["rate"][0]), d["cost"] > 0)]
    tile_html = "".join(f'<div class="tile{" warn" if w else ""}"><b>{_esc(v)}</b><span>{_esc(k)}</span></div>' for k, v, w in tiles)
    banner = ""
    if d["stopped"]:
        banner = f'<div class="banner">停止中: {_esc("、".join(d["stopped"]))}</div>'
    if d["problems"]:
        banner += '<div class="banner">読めないデータがあります（表示が不完全です）: ' + _esc(" / ".join(d["problems"][:10])) + "</div>"
    unset = [k for k, v, _ in d["limits"] if v is None]
    lim_rows = [[_esc(k), _esc(txt)] for k, _, txt in d["limits"]]
    proj_rows = []
    for pid, ts in sorted(d["projects"].items()):
        c = {k: sum(1 for t in ts if t.get("status") == k) for k in LABEL}
        proj_rows.append([_esc(pid), _esc(len(ts)), _esc(c["succeeded"]), _esc(c["running"] + c["queued"]),
                          _esc(c["awaiting_approval"]), _esc(c["failed"]), _esc(c["blocked"]), _esc(c["stopped"])])
    attention = [t for t in d["tasks"] if t.get("status") in ACTIVE | {"failed", "blocked", "stopped", "rejected"}]
    task_rows = [[_esc(t.get("task_id")), _esc(t.get("idempotency_key")), _esc(t.get("role_id")),
                  f'<span class="st {_esc(t.get("status"))}">{_esc(LABEL.get(t.get("status"), t.get("status")))}</span>',
                  _esc(t.get("attempts")), _esc(_ts(t.get("updated"))), _esc(_task_reason(t))] for t in attention]
    appr_rows = [[_esc(a.get("approval_id")), _esc(a.get("action")), _esc(a.get("risk")), _esc(a.get("summary")),
                  _esc(a.get("requested_by")), _esc(_ts(a.get("created")))] for a in d["pending"]]
    over_ids = {i.get("item_id") for i in d["overdue"]}
    item_rows = [[_esc(i.get("item_id")), _esc(i.get("assignee")), _esc(i.get("title")), _esc(i.get("risk")),
                  _esc(_ts(i.get("due"))), "期限超過" if i.get("item_id") in over_ids else ""] for i in d["items"]]
    stop_rows = [[_esc(_ts(e.get("at"))), _esc(e.get("event")), _esc(e.get("target")), _esc(e.get("actor")), _esc(e.get("reason"))]
                 for e in reversed(d["stop_log"][-20:])]
    log_rows = [[_esc(_ts(e.get("at"))), _esc(e.get("event")), _esc(e.get("approval_id")), _esc(e.get("actor")), _esc(e.get("note"))]
                for e in reversed(d["appr_log"][-20:])]
    rate, rate_day = d["rate"]
    cs = d["costs"]
    money = lambda v: _esc(cr.fmt_money(v, rate))  # noqa: E731
    cost_note = (f"<p class=\"muted\">費用はドル建てで記録しています。円は目安（1 ドル＝{_esc(f'{rate:g}')} 円、{_esc(rate_day)} 時点）で、上限の判定には使いません。</p>"
                 if rate else "<p class=\"muted\">費用はドル建てで記録しています。為替が未設定のため、円は表示していません。</p>")
    cost_html = (cost_note + _table(["区分", "キー", "費用"],
                 [["日別", _esc(k), money(v)] for k, v in sorted(cs["by_day"].items(), reverse=True)[:14]]
                 + [["役割別", _esc(k), money(v)] for k, v in sorted(cs["by_role"].items()) if v]
                 + [["案件別", _esc(k), money(v)] for k, v in sorted(cs["by_project"].items()) if v]
                 + [["合計", "", money(cs["total"])]]))
    gen = datetime.datetime.fromtimestamp(d["now"]).strftime("%Y-%m-%d %H:%M:%S")
    css = ("body{font:14px/1.6 system-ui,'Yu Gothic',sans-serif;margin:0;background:#f6f7f9;color:#1d2330}"
           "main{max-width:1100px;margin:0 auto;padding:16px}h1{font-size:20px}h2{font-size:16px;margin:28px 0 8px}"
           ".muted{color:#6b7280}.tiles{display:flex;flex-wrap:wrap;gap:10px}.tile{background:#fff;border:1px solid #d9dde4;"
           "border-radius:8px;padding:10px 14px;min-width:120px}.tile b{display:block;font-size:22px}.tile span{font-size:12px;color:#6b7280}"
           ".tile.warn{border-color:#c2410c;background:#fff4ec}.banner{background:#fee2e2;border:1px solid #b91c1c;color:#7f1d1d;"
           "padding:10px 14px;border-radius:8px;margin:10px 0}table{border-collapse:collapse;width:100%;background:#fff;font-size:13px}"
           "th,td{border:1px solid #e3e6ec;padding:5px 8px;text-align:left;vertical-align:top;word-break:break-all}th{background:#eef0f4}"
           ".st{font-weight:600}.st.failed,.st.blocked,.st.stopped,.st.rejected{color:#b91c1c}.st.awaiting_approval{color:#b45309}"
           "@media(prefers-color-scheme:dark){body{background:#12151b;color:#e5e7eb}.tile,table{background:#1b1f27;border-color:#343a46}"
           "th{background:#252a34}th,td{border-color:#343a46}.tile.warn{background:#3a2314}.banner{background:#3b1414;color:#fecaca}}")
    note = ('<p class="muted">この画面は表示のみです。承認・停止・再開は社長がチャット、または '
            '<code>scripts/stop_control.py</code> で行います。依頼の中身・実行結果は表示しません。外部へは送信していません。</p>')
    warn_unset = (f'<div class="banner">上限が未設定の項目が {len(unset)} 件あります。未設定の間は、該当の処理は起動しません。</div>' if unset else "")
    sec = lambda title, body: f"<section><h2>{_esc(title)}</h2>{body}</section>"  # noqa: E731
    return ("<!doctype html><html lang=\"ja\"><head><meta charset=\"utf-8\">"
            "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>AIVJ 管理画面</title>"
            f"<style>{css}</style></head><body><main><h1>AIVJ 管理画面 <span class=\"muted\">作成: {_esc(gen)}</span></h1>"
            f"{note}{banner}<div class=\"tiles\">{tile_html}</div>{warn_unset}"
            + sec("案件", _table(["案件", "タスク", "成功", "待機・実行中", "承認待ち", "失敗", "ブロック", "停止"], proj_rows))
            + sec("要対応・進行中のタスク", _table(["タスク", "キー", "役割", "状態", "試行", "更新", "直近の理由"], task_rows))
            + sec("承認待ち", _table(["承認 ID", "操作", "リスク", "概要", "依頼者", "依頼日時"], appr_rows))
            + sec("人間キュー（未対応）", _table(["ID", "担当", "件名", "リスク", "期限", ""], item_rows))
            + sec("停止ログ（直近 20 件）", _table(["日時", "操作", "対象", "実行者", "理由"], stop_rows))
            + sec("承認記録（直近 20 件）", _table(["日時", "イベント", "承認 ID", "実行者", "備考"], log_rows))
            + sec("費用の集計", cost_html)
            + sec("上限の設定状況", _table(["項目", "値"], lim_rows))
            + sec("未送信の通知（Gmail）", f"<p>{_esc(len(d['notify_unsent']))} 件が送信待ちです。送信は事前確認のうえ人間が行います。</p>")
            + "</main></body></html>")


def build(state_dir=DEFAULT_STATE, out=None, budgets_path=BUDGETS, now=None) -> Path:
    state = Path(state_dir)
    out = Path(out) if out else state / "管理画面.html"
    page = render(collect(state, budgets_path, now))
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(page)
    os.replace(tmp, out)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="管理画面（表示専用）の HTML を作る")
    ap.add_argument("--state-dir", default=str(DEFAULT_STATE))
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    print(f"作成しました: {build(a.state_dir, a.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
