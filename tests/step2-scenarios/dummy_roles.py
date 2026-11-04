"""試験用のダミー役割（LLM なし・費用ゼロ）。台帳（AI_ROLES.csv）には入れない。
新しいダミー役割は DUMMY_ROLES と HANDLERS に足すだけで動く（T2-11: 基盤の変更なし）。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class DummyRole:
    role_id: str
    dept_code: str = "DUMMY"
    impl_status: str = "implemented"


DUMMY_ROLES = {r.role_id: r for r in (DummyRole("DUMMY-A"), DummyRole("DUMMY-B"), DummyRole("DUMMY-FAIL"),
                                      DummyRole("DUMMY-NOTREADY", impl_status="definition_drafted"))}


def handler_a(payload, upstream):
    return {"value": payload.get("value", 1) + 1}, 0.0


def handler_b(payload, upstream):
    a = next(iter(upstream.values()), {"value": 0})
    return {"value": a["value"] * 10}, 0.0


def handler_fail(payload, upstream):
    raise RuntimeError("ダミーの失敗")


HANDLERS = {"DUMMY-A": handler_a, "DUMMY-B": handler_b, "DUMMY-FAIL": handler_fail}
