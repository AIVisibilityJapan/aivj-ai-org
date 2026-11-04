"""タスクエンジン（STEP 2 / 2-3）。ファイル管理方式（D-025: API・DB なし、費用ゼロ）。

- タスク 1 件 = 1 つの JSON ファイル（実行状態フォルダ/tasks/<task_id>.json）。
- 二重実行防止: 受付時は冪等キー、取得時は排他ロック（O_EXCL）。
- 再試行: 上限は設定から渡す。未設定（None）なら起動拒否（fail closed）。
- 停止: 停止指定ファイル（all / 部コード / role_id）。停止中は取得できない。
- 承認が必要なタスクは awaiting_approval で止め、承認されるまで取得できない（2-5 で接続）。
- 割当可否は role_registry.assignability に従う。
標準ライブラリのみ。実行状態は Git に置かない（.gitignore: データ/実行状態/）。
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

QUEUED, RUNNING, SUCCEEDED, FAILED, STOPPED, AWAITING = (
    "queued", "running", "succeeded", "failed", "stopped", "awaiting_approval")
TERMINAL = {SUCCEEDED, FAILED, STOPPED}


class EngineError(Exception):
    pass


def _now() -> float:
    return time.time()


def _safe(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._\-ぁ-んァ-ヶ一-龠ー]+", name):
        raise EngineError(f"不正な識別子: {name!r}")
    return name


class TaskEngine:
    def __init__(self, state_dir, limits: dict, roles: dict | None = None, clock=_now):
        """limits: {'max_retries': int|None, 'max_runtime_seconds': int|None}
        roles: {role_id: Role}（role_registry.load_roles の結果を辞書化）。None なら役割検査を行わない。"""
        self.dir = Path(state_dir)
        self.tasks = self.dir / "tasks"
        self.locks = self.dir / "locks"
        self.tasks.mkdir(parents=True, exist_ok=True)
        self.locks.mkdir(parents=True, exist_ok=True)
        self.limits = limits
        self.roles = roles
        self.clock = clock

    # ---- 入出力 ----
    def _path(self, task_id: str) -> Path:
        return self.tasks / f"{_safe(task_id)}.json"

    def get(self, task_id: str) -> dict:
        with open(self._path(task_id), encoding="utf-8") as f:
            return json.load(f)

    def _save(self, t: dict) -> None:
        t["updated"] = self.clock()
        tmp = self._path(t["task_id"]).with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(t, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path(t["task_id"]))

    def _log(self, t: dict, event: str, detail: str = "") -> None:
        t.setdefault("history", []).append({"at": self.clock(), "event": event, "detail": detail})

    def all_tasks(self) -> list[dict]:
        out = []
        for p in sorted(self.tasks.glob("*.json")):
            with open(p, encoding="utf-8") as f:
                out.append(json.load(f))
        return out

    # ---- 停止 ----
    def _stop_file(self) -> Path:
        return self.dir / "停止.json"

    def stopped(self) -> set[str]:
        p = self._stop_file()
        if not p.exists():
            return set()
        with open(p, encoding="utf-8") as f:
            return set(json.load(f))

    def stop(self, target: str) -> None:
        """target: 'all' / 部コード（例 D07）/ role_id。"""
        s = self.stopped() | {target}
        self._write_stop(s)

    def resume(self, target: str) -> None:
        self._write_stop(self.stopped() - {target})

    def _write_stop(self, s: set[str]) -> None:
        tmp = self._stop_file().with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sorted(s), f, ensure_ascii=False)
        os.replace(tmp, self._stop_file())

    # ---- 受付 ----
    def submit(self, idempotency_key: str, role_id: str, payload: dict | None = None,
               requires_approval: bool = False) -> dict:
        """同じ冪等キーは同じタスクを返す（重複作成しない）。"""
        _safe(idempotency_key)
        for t in self.all_tasks():
            if t["idempotency_key"] == idempotency_key:
                return t
        t = {"task_id": "T-" + uuid.uuid4().hex[:12], "idempotency_key": idempotency_key,
             "role_id": role_id, "payload": payload or {}, "attempts": 0,
             "status": AWAITING if requires_approval else QUEUED, "created": self.clock(),
             "lease_until": None, "worker": None, "result": None, "history": []}
        self._log(t, "submitted", "承認待ち" if requires_approval else "")
        self._save(t)
        return t

    def approve(self, task_id: str, approver: str) -> dict:
        """承認の記録は承認キュー（2-5）が行う。ここでは状態遷移のみ。"""
        t = self.get(task_id)
        if t["status"] != AWAITING:
            raise EngineError(f"承認待ちではない: {t['status']}")
        t["status"] = QUEUED
        self._log(t, "approved", approver)
        self._save(t)
        return t

    # ---- 実行 ----
    def _check_limits(self) -> None:
        for k in ("max_retries", "max_runtime_seconds"):
            v = self.limits.get(k)
            if not isinstance(v, int) or isinstance(v, bool) or v < 0 or (k == "max_runtime_seconds" and v == 0):
                raise EngineError(f"上限が未設定のため起動しません: {k}")

    def _lock(self, task_id: str):
        try:
            fd = os.open(self.locks / f"{_safe(task_id)}.lock", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return None
        os.close(fd)
        return self.locks / f"{task_id}.lock"

    def claim(self, worker: str) -> dict | None:
        """実行可能なタスクを 1 件取得する。無ければ None。"""
        self._check_limits()
        stopped = self.stopped()
        for t in self.all_tasks():
            if t["status"] != QUEUED:
                continue
            reason = self._blocked(t, stopped)
            if reason:
                continue
            lock = self._lock(t["task_id"])
            if lock is None:
                continue
            try:
                t = self.get(t["task_id"])           # ロック後に再読込（取得競合対策）
                if t["status"] != QUEUED:
                    continue
                t["status"] = RUNNING
                t["attempts"] += 1
                t["worker"] = worker
                t["lease_until"] = self.clock() + self.limits["max_runtime_seconds"]
                self._log(t, "claimed", f"{worker} / 試行 {t['attempts']}")
                self._save(t)
                return t
            finally:
                os.unlink(lock)
        return None

    def _blocked(self, t: dict, stopped: set[str]) -> str | None:
        if self.roles is not None:
            role = self.roles.get(t["role_id"])
            if role is None:
                return "役割が台帳にない"
            from_rr = _assignability(role, stopped)
            if not from_rr[0]:
                return from_rr[1]
        elif "all" in stopped or t["role_id"] in stopped:
            return "停止中"
        return None

    def complete(self, task_id: str, worker: str, result=None) -> dict:
        t = self._running(task_id, worker)
        t.update(status=SUCCEEDED, result=result, lease_until=None)
        self._log(t, "succeeded")
        self._save(t)
        return t

    def fail(self, task_id: str, worker: str, reason: str) -> dict:
        """失敗を記録。再試行上限内なら queued へ戻し、超えたら failed（停止して人間へ）。"""
        t = self._running(task_id, worker)
        t["lease_until"] = None
        if t["attempts"] > self.limits["max_retries"]:
            t["status"] = FAILED
            self._log(t, "failed", f"再試行上限超過: {reason}")
        else:
            t["status"] = QUEUED
            self._log(t, "retry_scheduled", reason)
        self._save(t)
        return t

    def _running(self, task_id: str, worker: str) -> dict:
        t = self.get(task_id)
        if t["status"] != RUNNING or t["worker"] != worker:
            raise EngineError(f"このワーカーの実行中タスクではない: {t['status']}/{t['worker']}")
        return t

    def reap_expired(self) -> list[str]:
        """リース切れ（応答なし）を失敗として扱う。"""
        out = []
        for t in self.all_tasks():
            if t["status"] == RUNNING and t["lease_until"] is not None and t["lease_until"] < self.clock():
                self.fail(t["task_id"], t["worker"], "リース切れ（応答なし）")
                out.append(t["task_id"])
        return out


def _assignability(role, stopped):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
    import role_registry as rr
    return rr.assignability(role, stopped)
