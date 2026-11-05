"""地域 AIV 分析 AI（AI-03-01）の道具: 正式データの読み取りと整理。読み取り専用・外部通信なし。

- 再測定・再計算・API 送信・Mart への書込みはしない。値は正式データにある文字列をそのまま使う（数値を作らない）。
- 版・SHA が固定（pins.yaml）と違えば止まる。自治体が見つからない／重複していれば止まる。
- 『0%』と『欠損』を区別する: この値ファイルには状態列がないため、0.0% は UNVERIFIED_ZERO（Mart で未確認の 0）とする。
  資源が『―』のものは NOT_AVAILABLE。0 に変えない。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

PINS = Path(__file__).with_name("pins.yaml")


class ReaderStop(Exception):
    """fail closed: 理由を添えて止める。人間キューに載せる対象。"""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:  # 読み取り専用
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_pins(path: Path = PINS) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_values(values_path, pins: dict | None = None) -> tuple[list, dict]:
    pins = pins or load_pins()
    p = Path(values_path)
    if not p.is_file():
        raise ReaderStop(f"値ファイルがない: {p}")
    sha = _sha256(p)
    want = pins["report_values"]["sha256"]
    if not want or sha != want:
        raise ReaderStop(f"値ファイルの SHA が固定と違う（固定 {want}／実際 {sha}）。読み取りを止める")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ReaderStop("値ファイルの形が想定と違う")
    return data, {"file": p.name, "sha256": sha, "selector_pinned": pins["report_values"]["selector"]}


def _state_rate(s: str) -> str:
    if s is None or s in ("", "―", "—"):
        return "NOT_AVAILABLE"
    return "UNVERIFIED_ZERO" if s.strip() in ("0%", "0.0%") else "FORMAL_VALUE"


def _check_integrity(r: dict) -> list:
    sf, errs = r["source_fields"], []
    pairs = {"SCORE_RATE_1": "national_rate", "SCORE_RATE_2": "region_rate", "SCORE_RATE_3": "prefecture_rate",
             "SCORE_GRADE_1": "national_grade", "SCORE_GRADE_2": "region_grade", "SCORE_GRADE_3": "prefecture_grade",
             "SCORE_SUB_1": "national_band", "SCORE_SUB_2": "region_band", "SCORE_SUB_3": "prefecture_band",
             "SCORE_TH_2": "region_header", "SCORE_TH_3": "prefecture", "NEG_STATUS": "negative_status"}
    for a, b in pairs.items():
        if sf.get(a) != r.get(b):
            errs.append(f"{a}≠{b}")
    if sf.get("NEG_COUNT") != f"{r['negative_count']}件":
        errs.append("NEG_COUNT≠negative_count")
    return errs


def get_municipality(records: list, name: str | None = None, municipality_id: str | None = None) -> dict:
    hit = [r for r in records if (municipality_id and r["municipality_id"] == municipality_id)
           or (name and not municipality_id and r["municipality"] == name)]
    if not hit:
        raise ReaderStop(f"自治体が見つからない: {name or municipality_id}（推測で別の自治体を使わない）")
    if len(hit) > 1:
        raise ReaderStop(f"自治体が複数ある: {name or municipality_id}。municipality_id で指定する")
    return hit[0]


PENDING_MARK = "PENDING_FORMAL_POINTER_APPROVAL"


def activation_notice(rec: dict) -> str | None:
    """根拠データが『正式ポインタ承認待ち』なら、社長確認に添える注記を返す（使うのは止めない。D-049）。"""
    st = (rec.get("selector_metadata") or {}).get("activation_state") or ""
    if PENDING_MARK in st:
        return f"根拠データが正式ポインタ承認待ちです（activation_state={st}）。自治体への送信は、承認されるまで止めてください。"
    return None


def organize(rec: dict, source: dict, pins: dict | None = None) -> dict:
    """1 自治体の値を、レポート制作 AI が使う形に整理する（値は書き換えない）。"""
    pins = pins or load_pins()
    errs = _check_integrity(rec)
    if errs:
        raise ReaderStop(f"根拠データの内部が食い違う: {errs}")
    pop = pins["population"]
    res = []
    for i, x in enumerate(rec["resources"], 1):
        name = x["asset_name"]
        res.append({"no": i, "name": None if name == "―" else name, "display": name, "state": "NOT_AVAILABLE" if name == "―" else "FORMAL_VALUE",
                    "origin": x.get("source")})
    metrics = {
        "appearance_rate": {"unit": f"全国{pop['appearance']}自治体を母数とする出現率（回答への登場割合）",
                            "scopes": {k: {"display": rec[f"{k}_rate"], "state": _state_rate(rec[f"{k}_rate"])}
                                       for k in ("national", "region", "prefecture")}},
        "apa_rank": {"unit": f"全国{pop['apa_rank']}自治体の APA 総合順位",
                     "national": {"rank": rec["national_rank"], "population": pop["apa_rank"], "grade": rec["national_grade"], "band": rec["national_band"]},
                     "region": {"name": rec["region_header"], "rank": rec["region_rank"], "population": rec["region_population"], "grade": rec["region_grade"], "band": rec["region_band"]},
                     "prefecture": {"name": rec["prefecture"], "rank": rec["prefecture_rank"], "population": rec["prefecture_population"], "grade": rec["prefecture_grade"], "band": rec["prefecture_band"]}},
        "negative": {"status": rec["negative_status"], "count": rec["negative_count"]},
    }
    return {"municipality": {k: rec[k] for k in ("prefecture", "municipality", "municipality_id", "official_code", "report_id")},
            "metrics": metrics, "resources": res,
            "report_fields": dict(rec["source_fields"]),  # FMT の図形名→文字（正式データのまま）
            "provenance": {**source, "record_selector": rec["selector_metadata"]["selector_version"],
                           "note": "2 つの集計単位（出現率 1,741／ランキング 1,719）は名前で結合していない"},
            "notices": [n for n in [activation_notice(rec)] if n],
            "notes": ["UNVERIFIED_ZERO は、値ファイルに状態列がないため、Mart で『明示的な 0』か『行なし』かを未確認"]}


def read_municipality(values_path, name: str | None = None, municipality_id: str | None = None) -> dict:
    records, src = load_values(values_path)
    return organize(get_municipality(records, name, municipality_id), src)
