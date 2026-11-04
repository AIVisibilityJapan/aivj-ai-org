"""役割台帳の取込と整合検証（STEP 2 / 2-2）。

正本は 文書/設計/AI_ROLES.csv。各役割の role.yaml、設定/org.yaml、設定/services.yaml、
サービス/*/service.yaml、設定/approval-rules.yaml と突き合わせ、食い違いをすべて列挙する。
標準ライブラリと PyYAML のみを使う。API・DB・外部通信は使わない。
"""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

CSV_PATH = "文書/設計/AI_ROLES.csv"
TYPES = {"AI COO", "部長 AI", "係担当 AI"}
RISKS = {"low", "mid", "high"}
STEPS = {f"STEP{i}" for i in range(2, 7)}
IMPL_STATUSES = {"not_implemented", "definition_drafted", "implemented"}
HUMAN_ESCALATION = {"社長"}
CONFIG_DIR = "設定"
SERVICES_DIR = "サービス"
AGENTS_DIR = "src/AI社員"
EXPECTED = {"roles": 59, "coo": 1, "heads": 7, "staff": 51, "departments": 7, "sections": 25, "units": 51, "services": 12, "pilots": 6}


@dataclass(frozen=True)
class Role:
    role_id: str
    role_name: str
    type: str
    dept_code: str | None
    dept: str
    section: str | None
    unit: str | None
    service_responsibility: str | None
    max_risk_tier: str
    human_checkpoint: str
    escalate_to: str
    build_step: str
    pilot: bool
    impl_status: str
    folder: str


def _none(v: str) -> str | None:
    return None if v in ("-", "", None) else v


def _read_yaml(path: Path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_roles(root: Path) -> list[Role]:
    with open(root / CSV_PATH, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return [Role(
        role_id=r["role_id"], role_name=r["role_name"], type=r["type"], dept_code=_none(r["dept_code"]), dept=r["dept"],
        section=_none(r["section_ka"]), unit=_none(r["unit_kakari"]), service_responsibility=_none(r["service_responsibility"]),
        max_risk_tier=r["max_risk_tier"], human_checkpoint=r["human_checkpoint"], escalate_to=r["escalate_to"],
        build_step=r["build_step"], pilot=(r["pilot_6"] == "Y"), impl_status=r["impl_status"], folder=r["folder"]) for r in rows]


def validate(root: Path | str) -> tuple[list[Role], list[str], list[str]]:
    """戻り値: (役割一覧, エラー一覧, 情報一覧)。エラーが空なら整合している。"""
    root = Path(root)
    errors: list[str] = []
    info: list[str] = []
    roles = load_roles(root)
    ids = [r.role_id for r in roles]
    by_id = {r.role_id: r for r in roles}

    # --- 件数・一意性 ---
    for rid in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"[台帳] role_id が重複: {rid}")
    n = {"roles": len(roles), "coo": sum(r.type == "AI COO" for r in roles), "heads": sum(r.type == "部長 AI" for r in roles),
         "staff": sum(r.type == "係担当 AI" for r in roles), "pilots": sum(r.pilot for r in roles),
         "departments": len({r.dept_code for r in roles if r.dept_code}),
         "sections": len({(r.dept_code, r.section) for r in roles if r.section}),
         "units": len({(r.dept_code, r.section, r.unit) for r in roles if r.unit})}
    for k, v in n.items():
        if v != EXPECTED[k]:
            errors.append(f"[台帳] {k} の件数が想定と違う: {v}（想定 {EXPECTED[k]}）")
    info.append("件数: " + " / ".join(f"{k}={v}" for k, v in n.items()))

    # --- 値の妥当性・運用ルール ---
    for r in roles:
        if r.type not in TYPES: errors.append(f"[台帳] {r.role_id}: type が不正: {r.type}")
        if r.max_risk_tier not in RISKS: errors.append(f"[台帳] {r.role_id}: max_risk_tier が不正: {r.max_risk_tier}")
        if r.build_step not in STEPS: errors.append(f"[台帳] {r.role_id}: build_step が不正: {r.build_step}")
        if r.impl_status not in IMPL_STATUSES: errors.append(f"[台帳] {r.role_id}: impl_status が不正: {r.impl_status}")
        if r.escalate_to not in by_id and r.escalate_to not in HUMAN_ESCALATION:
            errors.append(f"[台帳] {r.role_id}: escalate_to が存在しない: {r.escalate_to}")
        if r.escalate_to == r.role_id: errors.append(f"[台帳] {r.role_id}: escalate_to が自分自身")
        if r.type == "部長 AI" and r.build_step != "STEP6":
            errors.append(f"[運用ルール] {r.role_id}: 部長 AI は STEP6（Q-03/Q-18）。現在 {r.build_step}")
        if r.pilot and r.build_step not in {"STEP2", "STEP3", "STEP4"}:
            errors.append(f"[運用ルール] {r.role_id}: 初期6役割は STEP2〜4。現在 {r.build_step}")
        if not r.pilot and r.build_step in {"STEP2", "STEP3", "STEP4"}:
            errors.append(f"[運用ルール] {r.role_id}: 初期6役割以外が STEP2〜4: {r.build_step}")

    # --- role.yaml との照合 ---
    yaml_map = {"role_id": "role_id", "role_name": "role_name", "type": "type", "dept_code": "dept_code", "dept": "dept", "section": "section",
                "unit": "unit", "service_responsibility": "service_responsibility", "max_risk_tier": "max_risk_tier",
                "human_checkpoint": "human_checkpoint", "escalate_to": "escalate_to", "build_step": "build_step", "pilot": "pilot", "impl_status": "impl_status"}
    for r in roles:
        p = root / r.folder / "role.yaml"
        if not p.is_file():
            errors.append(f"[role.yaml] {r.role_id}: ファイルがない: {r.folder}/role.yaml"); continue
        try: y = _read_yaml(p)
        except yaml.YAMLError as e:
            errors.append(f"[role.yaml] {r.role_id}: 読み込めない: {e}"); continue
        for attr, key in yaml_map.items():
            if y.get(key) != getattr(r, attr):
                errors.append(f"[role.yaml] {r.role_id}: {key} が台帳と違う（台帳 {getattr(r, attr)!r} / yaml {y.get(key)!r}）")
        d = y.get("definition") or {}
        for k in ("purpose", "trigger", "inputs", "outputs", "tools", "permissions", "stop_conditions", "evaluation"):
            if k not in d: errors.append(f"[role.yaml] {r.role_id}: definition.{k} がない")
    # --- 台帳にない role.yaml ---
    known = {str((root / r.folder / "role.yaml").resolve()) for r in roles}
    for p in (root / AGENTS_DIR).rglob("role.yaml"):
        if str(p.resolve()) not in known: errors.append(f"[role.yaml] 台帳にない role.yaml: {p.relative_to(root).as_posix()}")

    # --- org.yaml ---
    org = _read_yaml(root / CONFIG_DIR / "org.yaml")
    for d in org["departments"]:
        rs = [r for r in roles if r.dept_code == d["code"]]
        if not rs: errors.append(f"[org.yaml] {d['code']}: 台帳に役割がない"); continue
        if d["name"] != rs[0].dept: errors.append(f"[org.yaml] {d['code']}: 部名が台帳と違う（{d['name']} / {rs[0].dept}）")
        parents = {Path(r.folder).parent.as_posix() for r in rs}
        if parents != {d["folder"]}: errors.append(f"[org.yaml] {d['code']}: フォルダが台帳と違う（{d['folder']} / {sorted(parents)}）")
        if not (root / d["folder"]).is_dir(): errors.append(f"[org.yaml] {d['code']}: フォルダがない: {d['folder']}")
        secs = len({r.section for r in rs if r.section}); units = sum(r.type == "係担当 AI" for r in rs)
        if d["sections"] != secs: errors.append(f"[org.yaml] {d['code']}: 課数が台帳と違う（{d['sections']} / {secs}）")
        if d["units"] != units: errors.append(f"[org.yaml] {d['code']}: 係数が台帳と違う（{d['units']} / {units}）")
    t = org["totals"]
    for key, val in (("departments", n["departments"]), ("sections", n["sections"]), ("units", n["units"]), ("ai_roles", n["roles"])):
        if t[key] != val: errors.append(f"[org.yaml] totals.{key} が台帳と違う（{t[key]} / {val}）")

    # --- サービス責任 ---
    svc = _read_yaml(root / CONFIG_DIR / "services.yaml")["services"]
    if len(svc) != EXPECTED["services"]: errors.append(f"[services] サービス数が想定と違う: {len(svc)}")
    for s in svc:
        o = by_id.get(s["owner_role"])
        if o is None or o.type != "部長 AI": errors.append(f"[services] {s['slug']}: owner_role が部長 AI として存在しない: {s['owner_role']}")
        sp = root / SERVICES_DIR / s["slug"] / "service.yaml"
        if not sp.is_file(): errors.append(f"[services] {s['slug']}: service.yaml がない"); continue
        if _read_yaml(sp).get("owner_role") != s["owner_role"]: errors.append(f"[services] {s['slug']}: service.yaml の owner_role が違う")

    # --- 承認ルール ---
    ar = _read_yaml(root / CONFIG_DIR / "approval-rules.yaml")
    for a in ar["actions"]:
        if a.get("final_approver") != "社長": errors.append(f"[approval-rules] {a.get('action')}: 最終承認者が社長でない")
        if not a.get("precheck"): errors.append(f"[approval-rules] {a.get('action')}: precheck がない")

    # --- 上限（情報） ---
    b = _read_yaml(root / CONFIG_DIR / "budgets.yaml")
    def leaves(x, path=""):
        if isinstance(x, dict):
            for k, v in x.items(): yield from leaves(v, f"{path}.{k}" if path else k)
        else: yield path, x
    unset = [k for k, v in leaves(b) if v is None and k != "monthly_limits.claude_platform_usd"]   # 月の Claude 利用上限は記録用（Pro は定額・取得不可、D-035）
    info.append(f"上限の未設定項目: {len(unset)}（未設定は起動しない。費用が発生する処理は都度社長確認）")
    return roles, errors, info


def assignability(role: Role, stopped: set[str] | frozenset[str] = frozenset()) -> tuple[bool, str]:
    """AI COO が割り当ててよいか（SYSTEM_ARCHITECTURE §6 の割当）。stopped は 'all' / 部コード / role_id の集合。"""
    if "all" in stopped or role.role_id in stopped or (role.dept_code and role.dept_code in stopped):
        return False, "停止中"
    if role.impl_status != "implemented":
        return False, f"未実装（impl_status={role.impl_status}）"
    return True, "割当可"


def export_json(roles: list[Role], path: Path | str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in roles], f, ensure_ascii=False, indent=2)
