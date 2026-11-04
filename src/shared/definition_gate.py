"""新しい AI 役割の定義案を検査する関門（STEP 3 / AI-07-01 の検査部分）。標準ライブラリ＋PyYAML のみ。外部通信なし。

T3-01 要件の必須項目チェック        check_requirements
T3-03/04/07 定義案が要件を超えない  check_definition（逸脱があれば承認依頼に進めない）
T3-05 別フォルダ実行で本番が変わらない  snapshot / diff / unexpected_changes
T3-09/10/11 承認依頼・承認後だけ登録   build_approval_request / register_with_approval
判断は機械的な規則による。迷うときは『要確認』ではなく『逸脱』として止める（fail closed）。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml

# 必須項目: 名称 → 許容する項目名（括弧書きを除いた完全一致）
REQUIRED = {
    "役割の名称": ["新しい AI 役割の名称"],
    "所属": ["所属", "所属（部・課・係）"],
    "目的": ["目的", "この AI は何のために働くか"],
    "成果物": ["成果物", "完成した成果物は何か"],
    "入力": ["入力", "入力（何を受け取るか）"],
    "出力": ["出力", "出力（何を返すか）"],
    "使ってよいツール": ["使ってよいツール"],
    "禁止事項": ["禁止", "禁止すること"],
    "リスク段階": ["リスク段階", "リスク段階の希望"],
    "社長が確認する地点": ["社長が確認する地点"],
    "止める条件": ["止める条件", "止める条件（異常時）"],
    "再試行の回数": ["再試行", "再試行の回数"],
    "合格の基準": ["合格基準", "合格の基準", "合格の基準（何ができれば合格か）"],
}
RISK_ORDER = {"low": 0, "mid": 1, "high": 2, "低": 0, "中": 1, "高": 2}
# 権限（付与されるもの）に含まれてはいけない語。要件の禁止事項に応じて有効にする
BANNED = {
    "外部への送信": (["送信", "ネットワーク", "http", "メール", "外部接続", "外部サービス"], ["送信", "ネットワーク"]),
    "費用の発生": (["費用", "課金", "有料", "api"], ["費用"]),
    "本番の変更": (["本番"], ["本番"]),
    "権限付与": (["権限付与", "権限を付与"], ["権限付与", "権限"]),
}


def _norm_key(k: str) -> str:
    return re.sub(r"[（(].*?[）)]", "", k).strip()


def parse_requirements(text: str) -> dict:
    """『- 項目: 値』行を、括弧書きを除いた項目名で辞書にする（同名は後の行で上書きしない）。"""
    out: dict = {}
    for line in text.splitlines():
        m = re.match(r"^\s*[-*]\s*([^:：]+?)\s*[:：]\s*(.*)$", line)
        if m:
            k = _norm_key(m.group(1))
            out.setdefault(k, m.group(2).strip())
    return out


def check_requirements(text: str) -> dict:
    """T3-01。必須項目が空・未記入なら missing に列挙する。"""
    req = parse_requirements(text)
    missing = []
    for name, keys in REQUIRED.items():
        vals = [req[k] for k in (_norm_key(x) for x in keys) if k in req]
        if not any(v and v not in ("未定", "TBD", "-") for v in vals):
            missing.append(name)
    return {"ok": not missing, "missing": missing, "fields": req}


def _field(req: dict, name: str) -> str:
    for k in REQUIRED[name]:
        v = req.get(_norm_key(k))
        if v:
            return v
    return ""


def check_definition(req_text: str, defn: dict) -> dict:
    """T3-03/04/07/08。要件に対して定義案が逸脱していれば violations に入れる。"""
    chk = check_requirements(req_text)
    violations = [f"要件に未記入の項目: {m}" for m in chk["missing"]]
    req = chk["fields"]
    d = defn.get("definition") or {}
    # リスク段階（T3-04）
    want = RISK_ORDER.get(_field(req, "リスク段階").strip().lower()) if _field(req, "リスク段階") else None
    have = RISK_ORDER.get(str(defn.get("max_risk_tier", "")).lower())
    if want is None or have is None:
        violations.append("リスク段階を判定できません（要件または定義案）")
    elif have > want:
        violations.append(f"定義案のリスク段階 {defn.get('max_risk_tier')} が要件 {_field(req, 'リスク段階')} より高い")
    # 権限（T3-03）
    perms = [str(x) for x in d.get("permissions", [])]
    grants = [str(x) for x in d.get("tools", [])] + [p for p in perms if not p.lstrip().startswith("禁止")]
    denies = " ".join([p for p in perms if p.lstrip().startswith("禁止")] + [str(x) for x in d.get("forbidden", [])])
    ban_text = _field(req, "禁止事項")
    for item, (grant_words, mention_words) in BANNED.items():
        if not any(w in ban_text for w in mention_words):
            continue
        hit = [g for g in grants for w in grant_words if w.lower() in g.lower()]
        if hit:
            violations.append(f"要件で禁止されている権限が含まれる（{item}）: {hit[0]}")
        if not any(w in denies for w in mention_words):
            violations.append(f"要件の禁止事項『{item}』が定義案の禁止に引き継がれていない")
    # 上限（T3-08）と費用（T3-07）
    lim = d.get("limits") or {}
    for k in ("max_retries", "max_runtime_seconds"):
        v = lim.get(k)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            violations.append(f"上限 {k} が未設定または不正（未設定の役割は起動しない）")
    cost = lim.get("max_cost_usd")
    needs_cost = not (isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost == 0)
    if needs_cost:
        if "費用" in ban_text:
            violations.append("要件で費用の発生が禁止されているのに、費用が発生する定義案（max_cost_usd が 0 ではない）")
        else:
            violations.append("費用が発生する定義案: 社長の費用確認が済むまで実行できない（承認依頼に費用を明記）")
    return {"ok": not violations, "violations": violations, "needs_cost_confirmation": needs_cost}


def may_run(check: dict, cost_confirmed_by_president: bool = False) -> bool:
    """T3-07。費用が発生する定義案は、社長の費用確認がなければ実行しない。"""
    if check["needs_cost_confirmation"] and not cost_confirmed_by_president:
        return False
    return not [v for v in check["violations"] if "費用確認が済むまで" not in v]


# ---- T3-05 別フォルダ実行の差分 ----
def snapshot(root, exclude: tuple = ()) -> dict:
    root = Path(root)
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_file() and not any(rel == e or rel.startswith(e.rstrip("/") + "/") for e in exclude):
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def diff(before: dict, after: dict) -> dict:
    return {"added": sorted(set(after) - set(before)), "removed": sorted(set(before) - set(after)),
            "changed": sorted(k for k in before.keys() & after.keys() if before[k] != after[k])}


def unexpected_changes(change: dict, allowed_prefixes: tuple) -> list:
    """許可した出力フォルダ以外に出た差分。空であれば本番側は変わっていない。"""
    allowed = tuple(p.rstrip("/") + "/" for p in allowed_prefixes)
    return sorted(f for k in ("added", "removed", "changed") for f in change[k] if not f.startswith(allowed))


# ---- T3-09/10/11 承認依頼と登録 ----
def file_hashes(paths) -> dict:
    return {Path(p).name: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}


def build_approval_request(queue, req_text: str, defn: dict, files: list, requested_by: str = "AI-07-01") -> tuple[dict, dict]:
    """逸脱がなければ承認依頼を作る。戻り値: (承認依頼, 内容＝承認時に提示する payload)。逸脱があれば ValueError。"""
    chk = check_definition(req_text, defn)
    blocking = [v for v in chk["violations"] if "費用確認が済むまで" not in v]
    if blocking:
        raise ValueError("逸脱があるため承認依頼に進めません: " + " / ".join(blocking))
    payload = {"role_id": defn.get("role_id"), "max_risk_tier": defn.get("max_risk_tier"),
               "definition": json.loads(json.dumps(defn.get("definition"), ensure_ascii=False, default=str)),
               "files": file_hashes(files), "needs_cost_confirmation": chk["needs_cost_confirmation"]}
    risk = "high" if chk["needs_cost_confirmation"] else {0: "low", 1: "mid", 2: "high"}[RISK_ORDER[str(defn["max_risk_tier"]).lower()]]
    a = queue.request(f"役割の登録: {defn.get('role_id')}", risk, payload, requested_by,
                      summary=f"{defn.get('role_name')}（{defn.get('max_risk_tier')}）")
    return a, payload


def register_with_approval(queue, approval_id: str, payload: dict, apply) -> object:
    """承認が有効（人間が承認・内容一致・期限内・未使用）のときだけ apply() を実行する。無効なら例外（記録は承認記録に残る）。"""
    queue.consume(approval_id, payload)
    return apply()
