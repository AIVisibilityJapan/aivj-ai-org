"""承認キューと人間キュー（STEP 2 / 2-5）。ファイル管理方式（D-025）。

承認キュー
- 承認依頼は「内容のハッシュ（SHA-256）」に結び付ける。承認後に内容が変わると無効（T3-09）。
- 承認・却下できるのは人間の最終承認者のみ（既定: 社長）。AI の役割 ID は拒否する。
- 承認には有効期限（ttl_hours）が必要。未設定（None）の間は承認を有効と認めない（fail closed）。
- 承認は 1 回だけ使える（使用済みの再利用は拒否）。
- 判断は追記専用の承認記録（承認記録.jsonl）に残す。
人間キュー
- 社長・業務委託者に渡す作業の一覧。高リスク作業の滞留上限（max_pending_high_risk）が未設定なら、
  高リスクの追加を拒否する（fail closed）。
- 通知は「送信待ち」ファイルに書くだけ。実際の送信は事前確認後に人間が行う（Q-08, Q-10）。
標準ライブラリのみ。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path

PENDING, APPROVED, REJECTED, USED = "pending", "approved", "rejected", "used"
RISKS = {"low", "mid", "high"}
FINAL_APPROVERS = {"社長"}
AI_ID = re.compile(r"^(AI-|TEST-)")


class ApprovalError(Exception):
    pass


def payload_hash(payload) -> str:
    """辞書・文字列・バイト列の内容ハッシュ。辞書はキー順を固定して正規化する。"""
    if isinstance(payload, bytes):
        data = payload
    elif isinstance(payload, str):
        data = payload.encode("utf-8")
    else:
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


class _Store:
    def __init__(self, base, name: str, clock):
        self.dir = Path(base) / name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.clock = clock

    def _p(self, i: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9._\-]+", i):
            raise ApprovalError(f"不正な識別子: {i!r}")
        return self.dir / f"{i}.json"

    def get(self, i: str) -> dict:
        try:
            with open(self._p(i), encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            raise ApprovalError(f"見つかりません: {i}")

    def save(self, d: dict, key: str) -> None:
        tmp = self._p(d[key]).with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._p(d[key]))

    def all(self) -> list[dict]:
        out = []
        for p in sorted(self.dir.glob("*.json")):
            with open(p, encoding="utf-8") as f:
                out.append(json.load(f))
        return out


class ApprovalQueue:
    def __init__(self, state_dir, limits: dict, clock=None, approvers=FINAL_APPROVERS):
        import time
        self.base = Path(state_dir)
        self.clock = clock or time.time
        self.limits = limits
        self.approvers = set(approvers)
        self.store = _Store(self.base, "approvals", self.clock)

    # ---- 記録（追記専用） ----
    def _record(self, event: str, d: dict, actor: str, note: str = "") -> None:
        with open(self.base / "承認記録.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": self.clock(), "event": event, "approval_id": d["approval_id"],
                                "actor": actor, "payload_hash": d["payload_hash"], "note": note},
                               ensure_ascii=False) + "\n")

    def history(self) -> list[dict]:
        p = self.base / "承認記録.jsonl"
        if not p.exists():
            return []
        with open(p, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]

    # ---- 依頼 ----
    def request(self, action: str, risk: str, payload, requested_by: str, summary: str = "") -> dict:
        if risk not in RISKS:
            raise ApprovalError(f"リスク段階が不正: {risk}")
        d = {"approval_id": "A-" + uuid.uuid4().hex[:12], "action": action, "risk": risk, "summary": summary,
             "requested_by": requested_by, "payload_hash": payload_hash(payload), "status": PENDING,
             "created": self.clock(), "decided_by": None, "decided_at": None, "expires_at": None, "reason": ""}
        self.store.save(d, "approval_id")
        self._record("requested", d, requested_by, action)
        return d

    def pending(self) -> list[dict]:
        return [a for a in self.store.all() if a["status"] == PENDING]

    # ---- 判断 ----
    def _check_human(self, actor: str) -> None:
        if not actor or AI_ID.match(actor) or actor not in self.approvers:
            raise ApprovalError(f"承認・却下できるのは人間の最終承認者のみです: {actor!r}")

    def approve(self, approval_id: str, actor: str, payload, reason: str = "") -> dict:
        """承認する。判断時点の内容ハッシュが依頼時と一致することを確認する（人間が見た内容の承認）。"""
        self._check_human(actor)
        ttl = self.limits.get("ttl_hours")
        if not isinstance(ttl, (int, float)) or isinstance(ttl, bool) or ttl <= 0:
            raise ApprovalError("承認の有効期限（ttl_hours）が未設定のため、承認を受け付けません")
        d = self.store.get(approval_id)
        if d["status"] != PENDING:
            raise ApprovalError(f"承認待ちではありません: {d['status']}")
        if payload_hash(payload) != d["payload_hash"]:
            raise ApprovalError("提示された内容が依頼時と異なります（ハッシュ不一致）")
        now = self.clock()
        d.update(status=APPROVED, decided_by=actor, decided_at=now, expires_at=now + ttl * 3600, reason=reason)
        self.store.save(d, "approval_id")
        self._record("approved", d, actor, reason)
        return d

    def reject(self, approval_id: str, actor: str, reason: str) -> dict:
        self._check_human(actor)
        if not reason or not reason.strip():
            raise ApprovalError("却下には理由の記録が必要です")
        d = self.store.get(approval_id)
        if d["status"] != PENDING:
            raise ApprovalError(f"承認待ちではありません: {d['status']}")
        d.update(status=REJECTED, decided_by=actor, decided_at=self.clock(), reason=reason)
        self.store.save(d, "approval_id")
        self._record("rejected", d, actor, reason)
        return d

    # ---- 使用時の検証 ----
    def verify(self, approval_id: str, payload) -> tuple[bool, str]:
        """実行直前に呼ぶ。承認済み・期限内・未使用・内容が同一、のすべてを満たすときだけ True。"""
        d = self.store.get(approval_id)
        if d["status"] == USED:
            return False, "使用済み"
        if d["status"] != APPROVED:
            return False, f"承認されていません（{d['status']}）"
        if self.clock() > d["expires_at"]:
            return False, "有効期限切れ"
        if payload_hash(payload) != d["payload_hash"]:
            return False, "内容が承認後に変更されています（ハッシュ不一致）"
        return True, "有効"

    def consume(self, approval_id: str, payload) -> dict:
        ok, why = self.verify(approval_id, payload)
        if not ok:
            self._record_denied(approval_id, why)
            raise ApprovalError(f"承認が有効ではありません: {why}")
        d = self.store.get(approval_id)
        d["status"] = USED
        self.store.save(d, "approval_id")
        self._record("used", d, d["decided_by"])
        return d

    def _record_denied(self, approval_id: str, why: str) -> None:
        d = self.store.get(approval_id)
        self._record("denied_use", d, "システム", why)

    def release_task(self, engine, task_id: str, approval_id: str, payload) -> dict:
        """承認が有効なときだけ、タスクエンジンの承認待ちタスクを実行可能にする。"""
        d = self.consume(approval_id, payload)
        return engine.approve(task_id, d["decided_by"])


class HumanQueue:
    def __init__(self, state_dir, limits: dict, clock=None):
        import time
        self.base = Path(state_dir)
        self.clock = clock or time.time
        self.limits = limits
        self.store = _Store(self.base, "human_queue", self.clock)

    def _notify(self, item: dict) -> None:
        """Gmail 通知の「送信待ち」を書くだけ。実際の送信は事前確認後に人間が行う。"""
        with open(self.base / "通知送信待ち.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": self.clock(), "to": item["assignee"], "channel": "Gmail",
                                "subject": f"【要対応】{item['title']}", "item_id": item["item_id"],
                                "sent": False}, ensure_ascii=False) + "\n")

    def add(self, assignee: str, title: str, risk: str, detail: str = "", due: float | None = None) -> dict:
        if risk not in RISKS:
            raise ApprovalError(f"リスク段階が不正: {risk}")
        if risk == "high":
            cap = self.limits.get("max_pending_high_risk")
            if not isinstance(cap, int) or isinstance(cap, bool) or cap < 0:
                raise ApprovalError("高リスク作業の滞留上限が未設定のため、追加できません")
            if sum(1 for i in self.open_items() if i["risk"] == "high") >= cap:
                raise ApprovalError(f"高リスク作業の滞留が上限（{cap}）に達しています")
        d = {"item_id": "H-" + uuid.uuid4().hex[:12], "assignee": assignee, "title": title, "risk": risk,
             "detail": detail, "due": due, "status": "open", "created": self.clock(), "done_by": None, "note": ""}
        self.store.save(d, "item_id")
        self._notify(d)
        return d

    def open_items(self) -> list[dict]:
        return [i for i in self.store.all() if i["status"] == "open"]

    def overdue(self) -> list[dict]:
        now = self.clock()
        return [i for i in self.open_items() if i["due"] is not None and i["due"] < now]

    def done(self, item_id: str, actor: str, note: str = "") -> dict:
        d = self.store.get(item_id)
        if d["status"] != "open":
            raise ApprovalError(f"未対応ではありません: {d['status']}")
        d.update(status="done", done_by=actor, note=note)
        self.store.save(d, "item_id")
        return d
