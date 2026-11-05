"""AI COO v0（STEP 2 / 2-6）。LLM・API・外部通信なし（費用ゼロ）。

動作（SYSTEM_ARCHITECTURE §6）: 受付 → 分解 → 割当 → 起動 → 監視 → 例外処理 → 報告。
COO がしないこと（構造で禁止）:
  - 承認結果の書込（承認キューは依頼・参照・承認済みの解放のみ。approve/reject を持たない）
  - 停止の再開（resume を持たない。停止は自動停止の結果として起きる）
  - 人間への契約上の指示（人間キューには「依頼」の形でのみ載せる）
  - 支出・発注・外部送信の実行（ここには実装しない）
初期（STEP 6 まで）は部長 AI を経由せず、係担当へ直接割り当てる（Q-03）。
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))

from approval_queue import ApprovalQueue, HumanQueue, payload_hash
import rejection_log as rlog
from task_engine import (AWAITING, BLOCKED, FAILED, QUEUED, REJECTED, SUCCEEDED, EngineError, Rejected, TaskEngine)

COO_ID = "AI-000"
REQUIRED = ("project_id", "client_id", "service_id", "workflow")


class COOError(Exception):
    pass


class _ApprovalsView:
    """COO が使える承認キューの操作だけを公開する（承認・却下は人間のみ）。"""
    def __init__(self, q: ApprovalQueue):
        self._q = q
        self.request = q.request
        self.pending = q.pending
        self.verify = q.verify
        self.release_task = q.release_task


class COO:
    def __init__(self, state_dir, limits: dict, roles: dict, handlers: dict, workflows: dict,
                 services: set, approval_limits: dict | None = None, clock=None, worker: str = COO_ID):
        import time
        self.clock = clock or time.time
        self.base = Path(state_dir)
        self.projects_dir = self.base / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.engine = TaskEngine(state_dir, limits, roles=roles, clock=self.clock)
        self.approvals = _ApprovalsView(ApprovalQueue(state_dir, approval_limits or {}, clock=self.clock))
        self.humans = HumanQueue(state_dir, approval_limits or {}, clock=self.clock)
        self.handlers, self.workflows, self.services, self.worker = handlers, workflows, set(services), worker
        self.rejection_log = self.base / "差戻しログ.md"   # 差戻しの記録は 1 ファイルに加筆（新しい順）

    # ---- 保存 ----
    def _pp(self, pid: str) -> Path:
        return self.projects_dir / f"{pid}.json"

    def get_project(self, pid: str) -> dict:
        with open(self._pp(pid), encoding="utf-8") as f:
            return json.load(f)

    def _save_project(self, p: dict) -> None:
        tmp = self._pp(p["project_id"]).with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._pp(p["project_id"]))

    def projects(self) -> list[dict]:
        out = []
        for f in sorted(self.projects_dir.glob("*.json")):
            with open(f, encoding="utf-8") as fh:
                out.append(json.load(fh))
        return out

    def _state(self) -> dict:
        p = self.base / "coo_state.json"
        if not p.exists():
            return {"escalated": [], "stop_log_seen": 0, "noticed": [], "streak_notified": []}
        with open(p, encoding="utf-8") as f:
            st = json.load(f)
        st.setdefault("noticed", []); st.setdefault("streak_notified", [])
        return st

    def _save_state(self, st: dict) -> None:
        tmp = self.base / "coo_state.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
        os.replace(tmp, self.base / "coo_state.json")

    # ---- 1. 受付 ----
    def register_project(self, project: dict) -> dict:
        for k in REQUIRED:
            if not str(project.get(k, "")).strip():
                raise COOError(f"必須項目がありません: {k}")
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", str(project["project_id"])):
            raise COOError("project_id は英数字・ハイフン・アンダースコアのみ使用できます")
        if project["service_id"] not in self.services:
            raise COOError(f"未登録のサービス区分: {project['service_id']}")
        if project["workflow"] not in self.workflows:
            raise COOError(f"未定義の業務フロー: {project['workflow']}")
        if self._pp(project["project_id"]).exists():            # 二重登録は同じ案件を返す
            return self.get_project(project["project_id"])
        p = {**project, "status": "registered", "steps": {}, "registered_at": self.clock()}
        self._save_project(p)
        return p

    # ---- 2. 分解 ----
    def _decompose(self, p: dict) -> None:
        wf = self.workflows[p["workflow"]]
        for step in wf["steps"]:                                  # 人間キュー登録に失敗したら何も作らない
            if step.get("risk") == "high":
                self.humans.add("社長", f"承認依頼: {p['project_id']} / 工程 {step['id']}", "high",
                                detail=f"{step.get('action', '高リスク操作')}（担当 {step['role']}）")
        ids = {}
        for step in wf["steps"]:
            key = f"{p['project_id']}.{step['id']}"
            payload = {**p.get("payload", {}), **step.get("payload", {})}
            high = step.get("risk") == "high"
            deps = [ids[d] for d in step.get("depends_on", [])]
            t = self.engine.submit(key, step["role"], payload, requires_approval=high, depends_on=deps)
            ids[step["id"]] = t["task_id"]
            rec = {"task_id": t["task_id"], "role": step["role"], "risk": step.get("risk", "low")}
            if high:
                ap_payload = {"project_id": p["project_id"], "step_id": step["id"], "role_id": step["role"],
                              "payload": payload}
                a = self.approvals.request(step.get("action", "高リスク操作"), "high", ap_payload, COO_ID,
                                           summary=f"{p['project_id']}/{step['id']}")
                rec.update(approval_id=a["approval_id"], approval_payload=ap_payload)
            p["steps"][step["id"]] = rec
        p["status"] = "running"
        self._save_project(p)

    # ---- 3〜5. 割当・起動・監視 ----
    def _release_approved(self, p: dict) -> None:
        for sid, rec in p["steps"].items():
            if "approval_id" not in rec:
                continue
            t = self.engine.get(rec["task_id"])
            if t["status"] == AWAITING and self.approvals.verify(rec["approval_id"], rec["approval_payload"])[0]:
                self.approvals.release_task(self.engine, rec["task_id"], rec["approval_id"], rec["approval_payload"])

    def _check_assignment(self) -> None:
        for t in self.engine.all_tasks():
            if t["status"] != QUEUED:
                continue
            why = self.engine.blocked_reason(t)
            if why and why != "停止中":                          # 停止中は待機。未実装などはブロックして人間へ
                self.engine.block(t["task_id"], why)
                self.humans.add("社長", f"割当不可: {t['role_id']}", "mid",
                                detail=f"{t['idempotency_key']}: {why}。兼務先の指定または役割の実装が必要です")

    def _run_ready(self) -> int:
        n = 0
        while True:
            t = self.engine.claim(self.worker)
            if t is None:
                return n
            n += 1
            h = self.handlers.get(t["role_id"])
            try:
                if h is None:
                    raise RuntimeError(f"実行処理が登録されていません: {t['role_id']}")
                up = {d: self.engine.get(d)["result"] for d in t.get("depends_on", [])}
                result, cost = h(t["payload"], up)
                r = self.engine.record_cost(t["task_id"], self.worker, cost)
                if r["status"] == FAILED:                         # 費用ガードが停止した
                    continue
                self.engine.complete(t["task_id"], self.worker, result)
            except EngineError:
                raise
            except Rejected as e:                                 # 差戻し: 再試行せず、連続失敗にも数えない（Q-15）
                self.engine.reject(t["task_id"], self.worker, e.reason, e.fix_points)
            except Exception as e:                                # noqa: BLE001 ハンドラの失敗は再試行へ
                self.engine.fail(t["task_id"], self.worker, f"{type(e).__name__}: {e}")

    # ---- 6. 例外処理 ----
    def _exceptions(self) -> None:
        st = self._state()
        for t in self.engine.all_tasks():
            if t["status"] == FAILED and t["task_id"] not in st["escalated"]:
                log = " / ".join(f"{h['event']}:{h['detail']}" for h in t["history"][-4:])
                self.humans.add("社長", f"失敗（再試行上限）: {t['role_id']} {t['idempotency_key']}", "mid",
                                detail=f"障害ログ: {log}。切り戻し案: このタスクの出力を破棄し、本番側は変更されていないことを確認、"
                                       f"原因確認後に再投入。")
                st["escalated"].append(t["task_id"])
        for t in self.engine.all_tasks():
            if t["status"] == REJECTED and t["task_id"] not in st["escalated"]:
                res = t.get("result") or {}
                fix = "／".join(res.get("fix_points") or []) or "（呼び出し側から指定なし）"
                self.humans.add("社長", f"差戻し: {t['role_id']} {t['idempotency_key']}", "mid",
                                detail=f"理由: {res.get('rejected')}。変更すべき箇所: {fix}。"
                                       f"原因の箇所は自動では変更しません。変更するかをご確認ください。"
                                       f"直したら新しい案件番号で登録し直してください（差戻しログ.md に記録）。")
                rlog.append(self.rejection_log, "差戻し", t["idempotency_key"], f"{t['role_id']}: {res.get('rejected')}",
                            fix, "（未変更。変更したら『変更の実施』を記録）", "AI COO", clock=self.clock)
                st["escalated"].append(t["task_id"])
                self._streak(t, st)
        for t in self.engine.all_tasks():                           # 注記（根拠データが承認待ち など）は止めずに社長へ添える
            note = (t.get("result") or {}).get("notice") if t["status"] == SUCCEEDED else None
            if note and t["task_id"] not in st["noticed"]:
                self.humans.add("社長", f"注記: {t['idempotency_key']}", "mid", detail=note)
                st["noticed"].append(t["task_id"])
        log = self.engine.stop_log()
        for e in log[st["stop_log_seen"]:]:
            if e["event"] == "auto_stop":
                self.humans.add("社長", f"自動停止: {e['target']}", "mid",
                                detail=f"{e['reason']}。再開は人間が判断します（stop_control.py resume）。")
        st["stop_log_seen"] = len(log)
        self._save_state(st)

    STREAK = 3

    def _streak(self, t: dict, st: dict) -> None:
        """同じ役割・同じ自治体で差戻しが連続したら、自動では止めず、連続の事実を社長へ強調して通知する（D-049）。"""
        key = lambda x: (x["role_id"], x["payload"].get("municipality") or x["payload"].get("municipality_id") or x["idempotency_key"])  # noqa: E731
        same = sorted((x for x in self.engine.all_tasks() if key(x) == key(t)), key=lambda x: x["created"])
        n = 0
        for x in reversed(same):
            if x["status"] != REJECTED:
                break
            n += 1
        if n >= self.STREAK and t["task_id"] == same[-1]["task_id"] and t["task_id"] not in st["streak_notified"]:
            who = f"{t['role_id']} / {key(t)[1]}"
            self.humans.add("社長", f"【{n}回連続】差戻し: {who}", "mid",
                            detail=f"同じ役割・同じ対象で差戻しが{n}回続いています。自動では止めていません。原因の箇所（ひな形・根拠データ・設定・定義）を"
                                   f"確認し、変更するかをご判断ください（差戻しログ.md に記録）。")
            rlog.append(self.rejection_log, "差戻しの連続", who, f"{n}回連続の差戻し", "原因の箇所を確認（自動では変更しない）",
                        "（未変更）", "AI COO", clock=self.clock)
            st["streak_notified"].append(t["task_id"])

    # ---- 外部からの依頼（社長以外）----
    def receive_request(self, requester: str, content: str) -> dict:
        """社長以外（営業担当など）からの依頼は受け付けない。依頼者と内容を人間キューに記録し、社長へ『依頼があった』と通知するだけ（D-049）。
        案件の登録元は社長だけ（register_project）。外部送信や監査の省略の依頼は断る旨を添える。"""
        who = str(requester or "").strip() or "（不明）"
        if who == "社長":
            raise COOError("社長の依頼は案件登録（register_project）で受け付けます")
        text = str(content or "").strip()[:500]
        risky = any(w in text for w in ("送信", "メール", "送付", "省略", "後回し", "監査なし", "先に"))
        self.humans.add("社長", f"依頼があった（未受付）: {who}", "mid",
                        detail=f"依頼内容: {text}。AI COO は受け付けていません。必要なら社長が案件として登録してください。"
                               + ("外部送信や監査の省略に当たる依頼は、承認なしでは実行しません。" if risky else ""))
        return {"accepted": False, "reason": "社長以外からの依頼は受け付けない（社長へ通知した）", "declined_risky": risky}

    def _update_projects(self) -> None:
        for p in self.projects():
            if p["status"] not in ("running", "attention"):
                continue
            states = [self.engine.get(r["task_id"])["status"] for r in p["steps"].values()]
            new = "done" if all(s == SUCCEEDED for s in states) else (
                "attention" if any(s in (FAILED, BLOCKED, REJECTED) for s in states) else "running")
            if new != p["status"]:
                p["status"] = new
                self._save_project(p)

    # ---- tick: 1 回の巡回 ----
    def tick(self) -> dict:
        for p in self.projects():
            if p["status"] == "registered":
                self._decompose(p)
        for p in self.projects():
            if p["status"] in ("running", "attention"):
                self._release_approved(p)
        self._check_assignment()
        self._run_ready()
        self.engine.reap_expired()
        self._run_ready()
        self._exceptions()
        self._update_projects()
        return self.report()

    # ---- 7. 報告 ----
    def report(self) -> dict:
        tasks = self.engine.all_tasks()
        count = lambda items, k: {x: sum(1 for i in items if i[k] == x) for x in sorted({i[k] for i in items})}  # noqa: E731
        return {"projects": count(self.projects(), "status"), "tasks": count(tasks, "status"),
                "awaiting_approval": [a["approval_id"] for a in self.approvals.pending()],
                "human_queue_open": len(self.humans.open_items()),
                "stopped": sorted(self.engine.stopped()), "cost_usd_total": self.engine.total_cost()}
