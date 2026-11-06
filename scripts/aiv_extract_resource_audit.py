"""観光資源の確認フロー: 原文→candidate→Evidence→Common/Alias→mapping→selector の系譜を『完全読み取り』で抽出する。

使い方（PowerShell、リポジトリ直下）:
    py scripts\aiv_extract_resource_audit.py

やること（すべて読み取り。正式データは変えない・開いて保存し直さない・移動も削除もしない）:
  1) 出現率 Mart と APA Mart（SQLite）を「読み取り専用・変更なし（mode=ro&immutable=1）」で開く
  2) 対象 3 自治体（鹿島市・芦屋町・川棚町）と、Gate が「未確認の具体候補が残る」とした 23 自治体の行だけを抜き出す
  3) 小さな監査用ファイル 8 点を 新しい出力フォルダ に書く（既存ファイルは上書きしない）
  4) 実行の前後で元データの SHA-256・サイズ・更新時刻を比べ、変化 0 件を確認する
外部通信なし・API 実行なし・費用 0。分類は『提案』であり、確定は独立監査（AI-06-05）と社長確認のあと。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

csv.field_size_limit(10**9)

R = Path(__file__).resolve().parents[1]
BASE = R / "データ" / "private" / "05-測定データ" / "AIV_NEW_PC_HANDOFF_20261105" / "01_AI_Visibility" / "01_正式成果物"
APPEARANCE_DB = BASE / "01_出現率" / "Report Mart v2.4" / "正式データ" / "01_appearance_rate_report_mart_v2_4_final_release.sqlite"
APA_DB = BASE / "02_APA" / "Report Mart" / "正式データ" / "01_MART" / "apa_v1_report_mart.sqlite"
WORK = R / "データ" / "private" / "06-STEP4作業" / "資源確認"
CSV_DIR = WORK / "入力"

CSV_FILES = {
    "selector": "diagnostic_selector_v1_5_51_formal_slots_common_v1_1_31_apa_mapping_v1_1_30.csv",
    "gate": "gate_municipality_status_v1_1_8.csv",
    "apa_map": "apa_common_asset_mapping_v1_1_30.csv",
    "lineage": "apa_common_asset_source_lineage_v1_1_30.csv",
    "master": "common_tourism_asset_master_v1_1_31.csv",
    "alias": "common_tourism_asset_alias_v1_1_24.csv",
    "relation": "common_asset_municipality_relation_v1_1_31.csv",
    "app_map": "appearance_common_asset_mapping_v1_1_12.csv",
}

# 優先 3 自治体: (名前, 都道府県, 今回追加された資源)
THREE = [
    ("鹿島市", "佐賀県", "ひぜん祐徳温泉 宝乃湯"),
    ("芦屋町", "福岡県", "芦屋海岸"),
    ("川棚町", "長崎県", "大崎自然公園"),
]
GATE_PENDING_REASON = "UNREVIEWED_CONCRETE_CANDIDATES_REMAIN"

SUFFIXES = [
    "海水浴場", "スキー場", "ゴルフ場", "キャンプ場", "動物園", "水族館", "美術館", "博物館", "資料館", "展望台", "遊歩道", "商店街",
    "花火大会", "温泉地", "温泉", "自然公園", "公園", "神社", "神宮", "大社", "寺", "院", "海岸", "海浜", "浜", "湖", "沼", "池",
    "山", "岳", "峠", "高原", "湿原", "渓谷", "峡", "滝", "川", "岬", "島", "灘", "湾", "城跡", "城", "館", "園", "牧場", "農園",
    "ダム", "橋", "漁港", "港", "古墳", "遺跡", "市場", "祭", "まつり", "宿場", "宿",
]
CH = "一-龥々〆ヶァ-ヶー0-9０-９A-Za-zＡ-Ｚａ-ｚ"
CAND_RE = re.compile(rf"(?:道の駅[{CH}]{{1,12}}|[{CH}]{{1,14}}(?:{'|'.join(sorted(SUFFIXES, key=len, reverse=True))}))")
GENERIC = {"温泉", "温泉地", "公園", "神社", "寺", "海岸", "浜", "湖", "山", "川", "島", "湾", "城", "館", "園", "港", "橋", "滝", "宿",
           "自然公園", "海浜", "高原", "渓谷", "岬", "灘", "祭", "まつり", "市場", "宿場", "古墳", "遺跡", "展望台", "遊歩道", "商店街", "ダム",
           "夏祭", "社寺", "古社寺", "寺院", "里山", "田園", "砂浜", "漁港", "軍港", "博物館", "美術館", "資料館", "水族館", "動物園", "海水浴場", "スキー場", "ゴルフ場", "キャンプ場"}
EXCLUDED_CLASSES = {"NON_SELF", "CLOSED", "NON_ASSET", "DUPLICATE", "GENERAL_EXPRESSION", "REJECTED"}
URL_RE = re.compile(r"https?://[^\s;,)]+")
OFFICIAL_RE = re.compile(r"(\.lg\.jp|\.go\.jp|^https?://(www\.)?(city|town|vill|pref)\.|\.pref\.|/pref\.)")


def nk(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"[\s・･·\-‐－―]", "", s).lower()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(8 * 1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def fingerprint(paths: list[Path], with_sha: bool) -> dict:
    out = {}
    for p in paths:
        st = p.stat()
        d = {"size": st.st_size, "mtime_ns": st.st_mtime_ns}
        if with_sha:
            d["sha256"] = sha256(p)
        out[str(p)] = d
    return out


def dir_listing(dirs: list[Path]) -> list[str]:
    names = []
    for d in dirs:
        for p in sorted(d.iterdir()):
            names.append(str(p))
    return names


def open_ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    return con


def has_table(con, name: str) -> bool:
    return con.execute("select 1 from sqlite_master where name=?", (name,)).fetchone() is not None


def urls_of(*texts: str) -> list[str]:
    seen, out = set(), []
    for t in texts:
        for u in URL_RE.findall(t or ""):
            if u not in seen:
                seen.add(u)
                out.append(u)
    return out


def evidence_label(urls: list[str]) -> str:
    if not urls:
        return "NONE"
    return "OFFICIAL_URL_RECORDED" if any(OFFICIAL_RE.search(u) for u in urls) else "URL_NON_OFFICIAL"


def write_csv(path: Path, rows: list[dict], cols: list[str]) -> None:
    if path.exists():
        raise RuntimeError(f"既存ファイルは上書きしません: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_text(path: Path, text: str) -> None:
    if path.exists():
        raise RuntimeError(f"既存ファイルは上書きしません: {path}")
    path.write_text(text, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--appearance-db", type=Path, default=APPEARANCE_DB)
    ap.add_argument("--apa-db", type=Path, default=APA_DB)
    ap.add_argument("--csv-dir", type=Path, default=CSV_DIR)
    ap.add_argument("--out-root", type=Path, default=WORK / "出力")
    ap.add_argument("--skip-sha", action="store_true", help="SHA-256 を省く（試験用。通常は付けない）")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = a.out_root / f"監査抽出_{stamp}"
    srcs = [a.appearance_db, a.apa_db] + [a.csv_dir / v for v in CSV_FILES.values()]
    for p in srcs:
        if not p.exists():
            print(f"見つかりません: {p}")
            return 2
    src_dirs = sorted({p.parent for p in srcs})
    for d in src_dirs:
        if out.resolve().is_relative_to(d.resolve()):
            print("出力先が元データのフォルダの中です。中止します。")
            return 2
    out.mkdir(parents=True, exist_ok=False)

    print("元データの SHA-256 を計算しています（APA は大きいので少し時間がかかります）…")
    before = fingerprint(srcs, not a.skip_sha)
    listing_before = dir_listing(src_dirs)

    # ---------- CSV ----------
    t = {k: read_csv(a.csv_dir / v) for k, v in CSV_FILES.items()}
    gate_by_id = {r["municipality_id"]: r for r in t["gate"]}
    muni_name = {r["municipality_id"]: r["municipality_name"] for r in t["gate"]}

    three_ids: dict[str, tuple[str, str]] = {}  # id -> (name, adopted asset name)
    for name, pref, asset in THREE:
        hit = [r for r in t["gate"] if r["municipality_name"] == name and r["prefecture"] == pref]
        if len(hit) != 1:
            print(f"対象自治体が一意に決まりません: {name} {pref} ({len(hit)})")
            return 2
        three_ids[hit[0]["municipality_id"]] = (name, asset)
    pend_ids = [r["municipality_id"] for r in t["gate"] if r["decision_reason"] == GATE_PENDING_REASON and r["municipality_id"] not in three_ids]
    all_ids = list(three_ids) + pend_ids

    sel_by_muni = defaultdict(list)
    for r in t["selector"]:
        sel_by_muni[r["municipality_id"]].append(r)
    sel_assets = {m: {r["common_asset_id"]: r["display_slot"] for r in rows if r["common_asset_id"]} for m, rows in sel_by_muni.items()}

    master = {r["asset_id"]: r for r in t["master"]}
    master_by_key = defaultdict(list)
    for r in t["master"]:
        master_by_key[nk(r["canonical_name"])].append(r)
    alias_by_key = defaultdict(list)
    alias_by_asset = defaultdict(list)
    for r in t["alias"]:
        alias_by_key[nk(r["alias"])].append(r)
        alias_by_asset[r["asset_id"]].append(r)
    rel_by_asset = defaultdict(list)
    for r in t["relation"]:
        rel_by_asset[r["asset_id"]].append(r)
    rel_assets_by_muni = defaultdict(set)
    for r in t["relation"]:
        rel_assets_by_muni[r["municipality_id"]].add(r["asset_id"])
    apa_map_by_asset, apa_map_by_comp = defaultdict(list), defaultdict(list)
    for r in t["apa_map"]:
        apa_map_by_asset[r["common_asset_id"]].append(r)
        if r["source_record_id"].startswith("apa_comparison:"):
            apa_map_by_comp[r["source_record_id"].split(":", 1)[1]].append(r)
    app_map_by_asset, app_map_by_cand = defaultdict(list), defaultdict(list)
    for r in t["app_map"]:
        app_map_by_asset[r["common_asset_id"]].append(r)
        if r["source_record_id"].startswith("appearance_candidate:"):
            app_map_by_cand[r["source_record_id"].split(":", 1)[1]].append(r)
    lineage_by = defaultdict(list)
    for r in t["lineage"]:
        lineage_by[(r["municipality_id"], r["comparison_id"])].append(r)

    # ---------- 照合・分類 ----------
    def asset_evidence(aid: str) -> list[str]:
        m = master.get(aid, {})
        return urls_of(m.get("notes", ""), *[x.get("notes", "") for x in alias_by_asset.get(aid, [])], *[x.get("notes", "") for x in rel_by_asset.get(aid, [])])

    def match(text: str, muni: str) -> dict:
        k = nk(text)
        hits = []
        for m in master_by_key.get(k, []):
            hits.append((m["asset_id"], "CANONICAL", ""))
        for al in alias_by_key.get(k, []):
            hits.append((al["asset_id"], "ALIAS", f'{al["alias"]}[{al["alias_status"]}]'))
        if hits:
            mine = [h for h in hits if h[0] in rel_assets_by_muni.get(muni, set())]
            h = (mine or hits)[0]
            return {"route": h[1], "asset_id": h[0], "via": h[2], "n_hits": len(hits)}
        if len(k) >= 3:
            for aid in rel_assets_by_muni.get(muni, set()):
                m = master.get(aid)
                if not m:
                    continue
                ck = nk(m["canonical_name"])
                if k in ck or ck in k:
                    return {"route": "PARTIAL", "asset_id": aid, "via": m["canonical_name"], "n_hits": 1}
        return {"route": "NONE", "asset_id": "", "via": "", "n_hits": 0}

    def classify(text: str, muni: str, mt: dict, app_hint: str = "") -> tuple[str, str]:
        k = nk(text)
        route, aid = mt["route"], mt["asset_id"]
        if route in ("CANONICAL", "ALIAS"):
            m = master.get(aid, {})
            status = (m.get("asset_status", "") or "").upper()
            if "MERGED" in status:
                return "DUPLICATE", f"マスター上で統合済み（{status}）"
            if status != "ACTIVE":
                return ("CLOSED" if any(x in status for x in ("CLOSED", "INACTIVE", "RETIRED", "DEPRECATED")) else "REVIEW_REQUIRED"), f"asset_status={status}"
            mine = [r for r in rel_by_asset.get(aid, []) if r["municipality_id"] == muni]
            if not mine:
                if rel_by_asset.get(aid):
                    return "NON_SELF", "マスターには載るが、この自治体との関係が無い（他自治体の資源）"
                return "REVIEW_REQUIRED", "マスターに載るが自治体関係の記録が無い"
            r = mine[0]
            rt, vs = (r["relation_type"] or "").upper(), (r["verification_status"] or "").upper()
            if vs != "VERIFIED":
                return "REVIEW_REQUIRED", f"関係の確認状態={vs}"
            if "NON_SELF" in rt:
                return "NON_SELF", f"relation_type={rt}（この自治体の資源ではない）"
            if "BROAD" in rt:
                return "BROAD_AREA_VERIFIED", f"relation_type={rt}"
            if "MULTI" in rt:
                return "MULTI_MUNICIPALITY", f"relation_type={rt}"
            if "SELF" in rt:
                return ("SELF_VERIFIED_ACTIVE" if route == "CANONICAL" else "EXISTING_ASSET_ALIAS"), f"relation_type={rt}（{'正式名' if route == 'CANONICAL' else 'エイリアス経由'}）"
            return "REVIEW_REQUIRED", f"relation_type={rt}（既存分類に当てはまらない）"
        if route == "PARTIAL":
            return "REVIEW_REQUIRED", f"既存資源『{mt['via']}』の一部／拡張表記（重複かどうかは監査で判断）"
        up = (app_hint or "").upper()
        if "NON_ASSET" in up:
            return "NON_ASSET", f"出現率側の分類={app_hint}"
        if any(x in up for x in ("CROSS", "OTHER_MUNI", "NON_SELF")):
            return "NON_SELF", f"出現率側の分類={app_hint}"
        stem = re.sub(r"[市町村区]$", "", nk(muni_name.get(muni, "")))
        if k in {nk(g) for g in GENERIC}:
            return "GENERAL_EXPRESSION", "一般名詞のみ（固有名が特定できない）"
        if k in (stem, nk(muni_name.get(muni, ""))) or len(k) <= 1:
            return "GENERAL_EXPRESSION", "自治体名そのもの／1文字（資源名ではない）"
        return "REVIEW_REQUIRED", "マスター・エイリアスに無く、公式 Evidence 未確認"

    # ---------- DB ----------
    app = open_ro(a.appearance_db)
    apa = open_ro(a.apa_db)
    try:
        ph = ",".join("?" * len(all_ids))
        three_ph = ",".join("?" * len(three_ids))

        # APA 自身の WIN 理由
        mc_rows = apa.execute(
            f"select municipality_id, evaluation_id, comparison_id, stage, round, opponent_id, opponent_name, result, recommended_reason, "
            f"self_positive_reason, source_path, source_sha256 from municipality_comparisons where municipality_id in ({ph})", all_ids).fetchall()
        result_values = Counter(r["result"] for r in mc_rows)
        wins = [r for r in mc_rows if str(r["result"]).upper() == "WIN"]
        comp_ids = {r["comparison_id"] for r in wins}
        winner_of, final_reason_of = {}, {}
        for r in apa.execute("select comparison_id, winner_id from comparisons"):
            if r["comparison_id"] in comp_ids:
                winner_of[r["comparison_id"]] = r["winner_id"]
        for r in apa.execute("select comparison_id, final_reason, is_corrected from reasons"):
            if r["comparison_id"] in comp_ids:
                final_reason_of[(r["comparison_id"])] = (r["final_reason"], r["is_corrected"])
        mentions = defaultdict(list)
        for r in apa.execute(f"select * from apa_self_resource_mentions where municipality_id in ({ph})", all_ids):
            mentions[(r["municipality_id"], r["comparison_id"])].append(dict(r))

        # 出現率 candidate
        cand_rows = [dict(r) for r in app.execute(
            f"select * from appearance_candidate_resolution where original_municipality_id in ({ph}) or resolved_municipality_id in ({ph}) or context_municipality_id in ({ph})",
            all_ids * 3).fetchall()]
        meta_app = dict(app.execute("select * from appearance_build_metadata").fetchone() or {})
        meta_apa = [dict(r) for r in apa.execute("select * from apa_resource_ranking_versions").fetchall()] if has_table(apa, "apa_resource_ranking_versions") else []
    finally:
        app.close()
        apa.close()

    # ---------- 01 APA 原文 ----------
    def extract_names(text: str) -> list[str]:
        seen, out_ = set(), []
        for m in CAND_RE.finditer(text or ""):
            s = m.group(0)
            if s not in seen:
                seen.add(s)
                out_.append(s)
        return out_

    win_rows_by_muni = defaultdict(list)
    f01 = []
    for r in sorted(wins, key=lambda x: (x["municipality_id"], x["evaluation_id"], x["comparison_id"])):
        m = r["municipality_id"]
        reason = r["recommended_reason"] or ""
        fin, corr = final_reason_of.get(r["comparison_id"], (None, None))
        ms = mentions.get((m, r["comparison_id"]), [])
        maps = apa_map_by_comp.get(r["comparison_id"], [])
        lin = lineage_by.get((m, r["comparison_id"]), [])
        names = extract_names(reason)
        win_rows_by_muni[m].append({"comparison_id": r["comparison_id"], "evaluation_id": r["evaluation_id"], "reason": reason, "names": names})
        if m in three_ids:
            f01.append({
                "municipality_id": m, "municipality_name": muni_name.get(m, ""), "comparison_id": r["comparison_id"],
                "evaluation_id": r["evaluation_id"], "stage": r["stage"], "round": r["round"],
                "winner_municipality_id": winner_of.get(r["comparison_id"], ""), "winner_name": muni_name.get(winner_of.get(r["comparison_id"], ""), ""),
                "opponent_id": r["opponent_id"], "opponent_name": r["opponent_name"], "result": r["result"],
                "reason_text": reason, "self_positive_reason": r["self_positive_reason"] or "",
                "final_reason": fin or "", "final_reason_is_corrected": corr if corr is not None else "",
                "reason_equals_final": "" if fin is None else (fin == reason),
                "lineage_reason_exact_equals": "" if not lin else all(x["reason_original_exact"] == reason for x in lin),
                "extracted_names_regex": " | ".join(names),
                "mention_resources": " | ".join(f'{x["resource_name_raw"]}→{x["canonical_resource_name"]}({x["verification_status"]})' for x in ms),
                "mention_ids": " | ".join(x["mention_id"] for x in ms),
                "apa_mapping": " | ".join(f'{x["common_asset_id"]}:{x["mapping_status"]}' for x in maps),
                "source_path": r["source_path"], "source_sha256": r["source_sha256"],
            })

    # ---------- 統合 candidate ----------
    # key (muni, nk(text)) -> info
    cands: dict[tuple[str, str], dict] = {}

    def get_c(m: str, text: str) -> dict:
        key = (m, nk(text))
        if key not in cands:
            cands[key] = {"muni": m, "texts": Counter(), "reason_comps": [], "mention_n": 0, "mention_ids": [], "app_ids": [], "app_ranks": [],
                          "app_hints": set(), "app_statuses": set(), "example_reason": "", "evals": set()}
        return cands[key]

    for m in all_ids:
        for w in win_rows_by_muni.get(m, []):
            for nm in w["names"]:
                c = get_c(m, nm)
                c["texts"][nm] += 1
                if w["comparison_id"] not in c["reason_comps"]:
                    c["reason_comps"].append(w["comparison_id"])
                c["evals"].add(w["evaluation_id"])
                if not c["example_reason"]:
                    c["example_reason"] = w["reason"]
        for (mm, cid), ms in mentions.items():
            if mm != m:
                continue
            for x in ms:
                for txt in {x["resource_name_raw"], x["canonical_resource_name"]}:
                    if txt:
                        c = get_c(m, txt)
                        c["texts"][txt] += 0
                        c["mention_n"] += 1 if txt == x["resource_name_raw"] else 0
                        if x["mention_id"] not in c["mention_ids"]:
                            c["mention_ids"].append(x["mention_id"])
                        if cid not in c["reason_comps"]:
                            c["reason_comps"].append(cid)
    f02 = []
    for r in cand_rows:
        for m in {r["original_municipality_id"], r["resolved_municipality_id"], r["context_municipality_id"]} & set(all_ids):
            c = get_c(m, r["candidate_name"])
            c["texts"][r["candidate_name"]] += 0
            c["app_ids"].append(r["candidate_row_id"])
            c["app_ranks"].append(r["candidate_rank"])
            c["app_hints"].add(r["original_classification"] or "")
            c["app_statuses"].add(r["final_resolution_status"] or "")
            if m in three_ids:
                aid = r["asset_id"] or ""
                mt = match(r["candidate_name"], m)
                maps = app_map_by_cand.get(r["candidate_row_id"], [])
                f02.append({
                    "municipality_id": m, "municipality_name": muni_name.get(m, ""), "candidate_id": r["candidate_row_id"],
                    "candidate_text": r["candidate_name"], "candidate_rank": r["candidate_rank"], "rank_class": r["rank_class"],
                    "canonical_candidate": r["canonical_asset_name"], "resolution_status": r["final_resolution_status"],
                    "original_classification": r["original_classification"], "resolution_method": r["resolution_method"],
                    "asset_id": aid, "asset_in_master": aid in master, "asset_status": master.get(aid, {}).get("asset_status", ""),
                    "active_asset_flag": r["active_asset_flag"], "coverage_bucket": r["coverage_bucket"],
                    "role_original_resolved_context": "/".join(x for x, v in (("original", r["original_municipality_id"]), ("resolved", r["resolved_municipality_id"]), ("context", r["context_municipality_id"])) if v == m),
                    "text_match_route": mt["route"], "text_match_asset_id": mt["asset_id"],
                    "appearance_mapping": " | ".join(f'{x["common_asset_id"]}:{x["mapping_status"]}' for x in maps),
                    "in_selector_slot": sel_assets.get(m, {}).get(aid, ""),
                    "question_id": r["question_id"], "scope": r["scope"], "category_id": r["category_id"], "source_row_key": r["source_row_key"],
                })

    def finalize(c: dict) -> dict:
        m = c["muni"]
        text = c["texts"].most_common(1)[0][0] if c["texts"] else ""
        # 照合は「正式名候補」を優先（canonical/alias に当たる表記があればそれを採用）
        best = None
        for tx in c["texts"]:
            mt = match(tx, m)
            if mt["route"] in ("CANONICAL", "ALIAS"):
                best, text = mt, tx
                break
            best = best or mt
        mt = best or {"route": "NONE", "asset_id": "", "via": "", "n_hits": 0}
        hint = " / ".join(sorted(h for h in c["app_hints"] if h))
        cls, why = classify(text, m, mt, hint)
        aid = mt["asset_id"]
        ev = asset_evidence(aid) if mt["route"] in ("CANONICAL", "ALIAS") else []
        rels = [r for r in rel_by_asset.get(aid, []) if r["municipality_id"] == m] if aid else []
        slot = sel_assets.get(m, {}).get(aid, "") if aid else ""
        apamaps = apa_map_by_asset.get(aid, []) if aid else []
        appmaps = app_map_by_asset.get(aid, []) if aid else []
        mapping_status = " | ".join(sorted({f'{x["source_namespace"]}:{x["mapping_status"]}' for x in apamaps + appmaps if x["municipality_id"] == m})) if aid else ""
        reason_count = len(c["reason_comps"])
        return {
            "municipality_id": m, "municipality_name": muni_name.get(m, ""), "candidate_text": text,
            "variants": " | ".join(c["texts"]), "apa_win_reason_count": reason_count, "apa_mention_count": c["mention_n"],
            "apa_comparison_ids_sample": " | ".join(c["reason_comps"][:5]), "apa_mention_ids_sample": " | ".join(c["mention_ids"][:3]),
            "appearance_candidate_ids": " | ".join(sorted(set(c["app_ids"]))[:8]),
            "appearance_min_rank": min(c["app_ranks"], key=lambda x: int(x) if str(x).isdigit() else 99) if c["app_ranks"] else "",
            "appearance_statuses": " / ".join(sorted(s for s in c["app_statuses"] if s)), "appearance_original_classification": hint,
            "common_match_route": mt["route"], "common_asset_id": aid, "common_canonical_name": master.get(aid, {}).get("canonical_name", ""),
            "common_asset_status": master.get(aid, {}).get("asset_status", ""), "alias_match": mt["via"] if mt["route"] == "ALIAS" else "",
            "municipality_relation": " | ".join(f'{r["relation_type"]}/{r["verification_status"]}/{r["relation_status"]}' for r in rels),
            "official_evidence": evidence_label(ev), "official_evidence_urls": " | ".join(ev[:3]),
            "mapping_status": mapping_status, "selector_status": f"IN_SLOT_{slot}" if slot else "NOT_IN_SELECTOR_TOP3",
            "adopted": bool(slot),
            "proposed_classification": cls, "basis_or_reason": why, "evals": " ".join(sorted(c["evals"])),
            "example_reason": c["example_reason"], "classification_note": "自動の提案（確定は独立監査 AI-06-05 と社長確認のあと）",
        }

    fin_all = [finalize(c) for c in cands.values()]
    fin_three = [f for f in fin_all if f["municipality_id"] in three_ids]
    fin_pend = [f for f in fin_all if f["municipality_id"] in pend_ids]
    for lst in (fin_three, fin_pend):
        lst.sort(key=lambda f: (f["municipality_id"], not f["adopted"], -int(f["apa_win_reason_count"]), f["candidate_text"]))
    cand_cols = list(fin_three[0].keys()) if fin_three else list(fin_all[0].keys())
    f04 = [f for f in fin_three if not f["adopted"]]

    # ---------- 03 系譜 ----------
    f03, chain_report = [], []

    def lrow(m, asset_name, link, **kw):
        base = {"municipality_id": m, "municipality_name": muni_name.get(m, ""), "adopted_asset": asset_name, "link": link}
        base.update(kw)
        f03.append(base)

    for m, (mname, aname) in three_ids.items():
        slot_rows = [r for r in sel_by_muni.get(m, []) if r["canonical_name"] == aname]
        if not slot_rows:
            chain_report.append({"municipality": mname, "asset": aname, "chain_complete": False, "missing": ["selector"]})
            continue
        s = slot_rows[0]
        aid = s["common_asset_id"]
        mrow = master.get(aid)
        canon_k = nk(mrow["canonical_name"]) if mrow else ""
        alias_keys = {nk(x["alias"]): x for x in alias_by_asset.get(aid, [])}
        flags = {"source": False, "master": bool(mrow), "name_connection": False, "relation": False, "mapping": False, "selector": True}
        lrow(m, aname, "MASTER", asset_id=aid, detail=json.dumps({k: mrow[k] for k in ("canonical_name", "asset_status", "verification_status", "first_source", "created_at", "notes")}, ensure_ascii=False) if mrow else "MISSING")
        for x in alias_by_asset.get(aid, []):
            lrow(m, aname, "ALIAS", asset_id=aid, detail=json.dumps({k: x[k] for k in ("alias", "alias_scope", "alias_status", "created_at", "notes")}, ensure_ascii=False))
        for x in rel_by_asset.get(aid, []):
            flags["relation"] |= x["municipality_id"] == m
            lrow(m, aname, "RELATION", asset_id=aid, detail=json.dumps({k: x[k] for k in ("municipality_id", "relation_type", "verification_status", "relation_status", "evidence_id", "notes")}, ensure_ascii=False))
        for x in apa_map_by_asset.get(aid, []):
            flags["mapping"] = True
            lrow(m, aname, "MAPPING_APA", asset_id=aid, detail=json.dumps({k: x[k] for k in ("source_record_id", "mapping_basis", "mapping_status", "resolution_action")}, ensure_ascii=False))
        for x in app_map_by_asset.get(aid, []):
            flags["mapping"] = True
            lrow(m, aname, "MAPPING_APPEARANCE", asset_id=aid, detail=json.dumps({k: x[k] for k in ("source_record_id", "mapping_basis", "mapping_status", "resolution_action")}, ensure_ascii=False))
        lrow(m, aname, "SELECTOR", asset_id=aid, detail=json.dumps({k: s[k] for k in ("display_slot", "source_tier", "source_namespace", "source_record_id", "promotion_reason", "verification_status", "asset_status")}, ensure_ascii=False))
        # 原文側（APA 理由）
        for x in apa_map_by_asset.get(aid, []):
            if not x["source_record_id"].startswith("apa_comparison:"):
                continue
            cid = x["source_record_id"].split(":", 1)[1]
            win = next((w for w in win_rows_by_muni.get(m, []) if w["comparison_id"] == cid), None)
            lin = [y for y in lineage_by.get((m, cid), []) if y["common_asset_id"] == aid]
            raws = sorted({y["resource_name_raw"] for y in lin} | {z["resource_name_raw"] for z in mentions.get((m, cid), []) if z.get("dictionary_asset_id") == aid})
            if not raws and win:
                raws = [n for n in win["names"] if nk(n) == canon_k or nk(n) in alias_keys]
            for raw in raws:
                via = "CANONICAL_EXACT" if nk(raw) == canon_k else (f'ALIAS:{alias_keys[nk(raw)]["alias"]}' if nk(raw) in alias_keys else "UNCONNECTED")
                flags["name_connection"] |= via != "UNCONNECTED"
                flags["source"] = True
                lrow(m, aname, "SOURCE_REASON", asset_id=aid, source_id=cid, raw_name=raw, connected_via=via,
                     detail=(win["reason"] if win else "(この比較の WIN 行が DB に無い)"))
            if not raws:
                flags["source"] |= bool(win)
                lrow(m, aname, "SOURCE_REASON", asset_id=aid, source_id=cid, raw_name="", connected_via="NO_RAW_NAME_FOUND", detail=win["reason"] if win else "")
        # 原文側（出現率 candidate）
        cids = [k for k, v in app_map_by_cand.items() if any(y["common_asset_id"] == aid for y in v)]
        for cr in cand_rows:
            if cr["candidate_row_id"] in cids or (cr["asset_id"] == aid):
                raw = cr["candidate_name"]
                via = "CANONICAL_EXACT" if nk(raw) == canon_k else (f'ALIAS:{alias_keys[nk(raw)]["alias"]}' if nk(raw) in alias_keys else ("ASSET_ID_LINK" if cr["asset_id"] == aid else "UNCONNECTED"))
                flags["name_connection"] |= via != "UNCONNECTED"
                flags["source"] = True
                lrow(m, aname, "SOURCE_CANDIDATE", asset_id=aid, source_id=cr["candidate_row_id"], raw_name=raw, connected_via=via,
                     detail=json.dumps({"rank": cr["candidate_rank"], "status": cr["final_resolution_status"], "classification": cr["original_classification"],
                                        "method": cr["resolution_method"], "asset_id": cr["asset_id"]}, ensure_ascii=False))
        # 別資源の確認（同じ自治体の他スロットと identity が別か）
        for o in sel_by_muni.get(m, []):
            if o["common_asset_id"] and o["common_asset_id"] != aid:
                ok = nk(o["canonical_name"])
                shared = ({nk(x["alias"]) for x in alias_by_asset.get(o["common_asset_id"], [])} | {ok}) & (set(alias_keys) | {canon_k})
                lrow(m, aname, "IDENTITY_CHECK", asset_id=aid, source_id=o["common_asset_id"], raw_name=o["canonical_name"],
                     connected_via="DISTINCT_ASSET" if not shared else "SHARED_NAME",
                     detail=f'他スロット『{o["canonical_name"]}』({o["common_asset_id"]}) とは asset_id が別。共有する名称キー: {sorted(shared) or "なし"}')
        miss = [k for k, v in flags.items() if not v]
        chain_report.append({"municipality": mname, "asset": aname, "asset_id": aid, "chain_complete": not miss, "missing": miss, "flags": flags})
    f03_cols = ["municipality_id", "municipality_name", "adopted_asset", "link", "asset_id", "source_id", "raw_name", "connected_via", "detail"]

    # ---------- 件数 ----------
    three_counts = {}
    for m, (mname, _a) in three_ids.items():
        fs = [f for f in fin_three if f["municipality_id"] == m]
        three_counts[mname] = {
            "apa_win_reason_rows": sum(1 for r in f01 if r["municipality_id"] == m),
            "appearance_candidate_rows": sum(1 for r in f02 if r["municipality_id"] == m),
            "unique_candidates": len(fs),
            "adopted": len({f["common_asset_id"] for f in fs if f["adopted"]}),
            "adopted_text_variants": sum(1 for f in fs if f["adopted"]),
            "excluded": sum(1 for f in fs if not f["adopted"] and f["proposed_classification"] in EXCLUDED_CLASSES),
            "review_required": sum(1 for f in fs if not f["adopted"] and f["proposed_classification"] == "REVIEW_REQUIRED"),
            "verified_but_not_top3": sum(1 for f in fs if not f["adopted"] and f["proposed_classification"] in ("SELF_VERIFIED_ACTIVE", "EXISTING_ASSET_ALIAS", "BROAD_AREA_VERIFIED", "MULTI_MUNICIPALITY")),
            "classification_counts": dict(Counter(f["proposed_classification"] for f in fs if not f["adopted"])),
        }

    # ---------- 書き出し ----------
    cols01 = list(f01[0].keys()) if f01 else ["municipality_id"]
    cols02 = list(f02[0].keys()) if f02 else ["municipality_id"]
    write_csv(out / "01_three_municipalities_apa_win_reasons.csv", f01, cols01)
    write_csv(out / "02_three_municipalities_appearance_candidates.csv", f02, cols02)
    write_csv(out / "03_three_municipalities_candidate_lineage.csv", f03, f03_cols)
    write_csv(out / "04_three_municipalities_rejected_review_required_candidates.csv", f04, cand_cols)
    write_csv(out / "05_remaining23_municipalities_candidate_extract.csv", fin_pend, cand_cols)

    # ---------- 再計測（変更ゼロの確認） ----------
    after = fingerprint(srcs, not a.skip_sha)
    listing_after = dir_listing(src_dirs)
    changed = [p for p in before if before[p] != after[p]]
    created = sorted(set(listing_after) - set(listing_before))
    removed = sorted(set(listing_before) - set(listing_after))

    manifest = {
        "extracted_at": dt.datetime.now().astimezone().isoformat(), "script": "scripts/aiv_extract_resource_audit.py",
        "sources": {Path(p).name: {"path": p, **v} for p, v in before.items()},
        "versions": {"selector": "1.5.51", "common_asset": "1.1.31", "alias": "1.1.24", "relation": "1.1.31", "apa_mapping": "1.1.30",
                     "appearance_mapping": "1.1.12", "gate": "1.1.8", "appearance_mart_build_metadata": meta_app, "apa_ranking_versions": meta_apa},
        "note": "selector 1.5.51 は追加後の現行版。追加前（1.5.49）は再現していない。",
    }
    write_text(out / "06_source_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))

    lineage_all_ok = all(c["chain_complete"] for c in chain_report) and len(chain_report) == len(THREE)
    validation = {
        "source_modification": len(changed), "source_modified_files": changed, "source_delete": len(removed), "source_move": 0,
        "source_new_files_in_source_dirs": created, "pointer_change": 0, "api_execution": 0, "network_access": 0,
        "sqlite_open_mode": "mode=ro&immutable=1", "output_dir": str(out),
        "apa_result_values_for_targets": dict(result_values),
        "appearance_original_classification_values": dict(Counter(r["original_classification"] for r in cand_rows)),
        "appearance_final_resolution_status_values": dict(Counter(r["final_resolution_status"] for r in cand_rows)),
        "three_municipalities": three_counts,
        "reason_text_vs_lineage_mismatch_rows": sum(1 for r in f01 if r["lineage_reason_exact_equals"] is False),
        "reason_text_vs_final_reason_mismatch_rows": sum(1 for r in f01 if r["reason_equals_final"] is False),
        "lineage_chain": chain_report, "lineage_all_traceable": lineage_all_ok,
        "remaining23": {"municipalities": len(pend_ids), "rows": len(fin_pend),
                        "classification_counts": dict(Counter(f["proposed_classification"] for f in fin_pend)),
                        "municipalities_with_win_reasons": len({r["municipality_id"] for r in wins if r["municipality_id"] in pend_ids})},
        "status": "COMPLETED" if not changed and not created and not removed else "SOURCE_CHANGED_CHECK_REQUIRED",
    }
    write_text(out / "07_readonly_extraction_validation.json", json.dumps(validation, ensure_ascii=False, indent=2, default=str))

    def lin_line(c):
        return f'{c["municipality"]}／{c["asset"]}: ' + ("全 6 段（原文・マスター・名称接続・関係・mapping・selector）が追える" if c["chain_complete"] else f'欠け={c["missing"]}')

    tc = three_counts
    summary = f"""# 読み取り専用の抽出 最終報告（{stamp}）

1. 抽出 status: {validation['status']}
2. 使用 source: 出現率 Mart v2.4 / APA Mart v1（SQLite、読み取り専用で開封）／ selector・Gate・Common Asset・Alias・関係・mapping・系譜の CSV 8 点
3. source version: selector 1.5.51 / Common Asset 1.1.31 / Alias 1.1.24 / 関係 1.1.31 / APA mapping 1.1.30 / 出現率 mapping 1.1.12 / Gate 1.1.8（追加後の現行版。1.5.49 は再現していない）
4. source SHA: 06_source_manifest.json に全ファイル分
5. 3 自治体の APA 原文抽出件数（自市区町村の WIN 理由）: {', '.join(f'{k} {v["apa_win_reason_rows"]}' for k, v in tc.items())}
6. 3 自治体の Appearance candidate 件数: {', '.join(f'{k} {v["appearance_candidate_rows"]}' for k, v in tc.items())}
7. 正式採用 candidate 数（selector Top3 入りの資源の数。表記ゆれは 1 件に数える）: {', '.join(f'{k} {v["adopted"]}' for k, v in tc.items())}
8. 除外 candidate 数（提案）: {', '.join(f'{k} {v["excluded"]}' for k, v in tc.items())}
9. REVIEW_REQUIRED 数（提案）: {', '.join(f'{k} {v["review_required"]}' for k, v in tc.items())}
   （正式資源だが Top3 外: {', '.join(f'{k} {v["verified_but_not_top3"]}' for k, v in tc.items())}）
10. 鹿島市 lineage: {lin_line(chain_report[0]) if len(chain_report) > 0 else '-'}
11. 芦屋町 lineage: {lin_line(chain_report[1]) if len(chain_report) > 1 else '-'}
12. 川棚町 lineage: {lin_line(chain_report[2]) if len(chain_report) > 2 else '-'}
13. 23 自治体抽出: {validation['remaining23']['municipalities']} 自治体・{validation['remaining23']['rows']} 行（分類の内訳 {validation['remaining23']['classification_counts']}）
14. source 変更件数: {validation['source_modification']}（削除 {validation['source_delete']}・移動 0・元フォルダへの新規ファイル {len(created)}）
15. pointer 変更件数: 0
16. API 実行件数: 0
17. 成果物 path: {out}

## 読み方の注意
- 分類（classification）は自動の**提案**です。確定は独立監査（AI-06-05）と社長確認のあとです。REJECTED は自動では付けません。
- candidate の具体名は、DB の既存抽出（apa_self_resource_mentions・出現率 candidate）に加え、WIN 理由原文から「固有名＋施設・地形の語尾」の規則で拾った**ヒューリスティック**です。ひらがなを含む名称（例: ひぜん祐徳温泉）は規則だけでは拾い切れません。取りこぼしの確認は監査で行います。
- 3 自治体の現行 selector に載る資源は『採用』、載らない正式資源は『Top3 外の正式資源』として別に数えています。
"""
    write_text(out / "08_final_summary.md", summary)
    print(summary)
    print("\n完了。出力フォルダ:", out)
    return 0 if validation["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
