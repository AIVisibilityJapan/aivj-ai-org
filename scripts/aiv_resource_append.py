#!/usr/bin/env python3
"""資源追記ツール（stage専用・追記専用）。設計: 文書/設計/資源追記ツール設計_20261109.md

- 入力（baseline）は読み取りのみ。実行前後のSHA256を比較し、変わっていれば失敗。
- 出力は --stage-root（存在しない新規フォルダ）だけ。正式ポインタ・Gate・PPTXには触れない。
- 追記指定CSVの各行を検査し、通らない行は unadopted.csv に理由つきで残す（--strict なら全件通らないと停止）。
- 対応する操作: (1) 既存資産の関係を SELF_RESOURCE に訂正（新行を追記＋旧行は SUPERSEDED）
                (2) エイリアス追加（衝突検査つき）
                (3) 空スロットの充填
  ※ 新規資産の作成は未対応（指定されたら停止）。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

REQUIRED = ["municipality_id", "asset_id", "measured_name", "existence_status", "address_original", "address_municipality",
            "official_evidence_url", "evidence_kind", "source_record_ids", "audit_ref", "president_confirmation_ref"]
OPTIONAL = ["alias", "relation_type_to"]
SLOT_COLS = ["municipality_id", "municipality_name", "display_slot", "common_asset_id", "canonical_name", "source_tier", "source_namespace",
             "source_record_id", "appearance_candidate_rank", "apa_source_information", "dedup_reason", "promotion_reason", "resource_scope",
             "relation_type", "relation_status", "relation_evidence_id", "verification_status", "asset_status"]


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def rd(p: Path) -> pd.DataFrame:
    return pd.read_csv(p, encoding="utf-8-sig", dtype=str).fillna("")


def bare(mid: str) -> str:
    return mid[5:] if mid.startswith("MUNI_") else mid


def pre(mid: str) -> str:
    return mid if mid.startswith("MUNI_") else "MUNI_" + mid


class Stop(Exception):
    pass


def check_row(r, master, alias, rel, spec_names, municipality_names):
    """1行の検査。問題があれば理由の文字列リストを返す。"""
    why = []
    for c in REQUIRED:
        if not str(r.get(c, "")).strip():
            why.append(f"必須項目が空: {c}")
    if why:
        return why
    if r["existence_status"].strip() != "確認済み":
        why.append(f"実在が確認済みでない: {r['existence_status']}")
    m = pre(r["municipality_id"])
    if m not in municipality_names:
        why.append(f"スロット表に存在しない自治体: {m}")
    if r["address_municipality"].strip() != municipality_names.get(m, "?"):
        why.append(f"住所の所在自治体が対象と一致しない: {r['address_municipality']} / 対象 {municipality_names.get(m)}")
    ma = master[master.asset_id == r["asset_id"]]
    if len(ma) != 1:
        why.append(f"資産IDがマスターに1件でない（{len(ma)}件）。新規資産の作成は未対応")
    else:
        a = ma.iloc[0]
        if a.asset_status != "ACTIVE" or a.verification_status != "VERIFIED":
            why.append(f"資産が ACTIVE/VERIFIED でない: {a.asset_status}/{a.verification_status}")
        if bare(m) not in [bare(x) for x in a.verified_municipality_ids.replace("|", ";").split(";") if x] + [bare(a.primary_municipality_id)]:
            why.append("マスター上の所属自治体に対象が含まれない")
        mn = r["measured_name"].strip()
        same = {a.canonical_name, r["alias"].strip() if r.get("alias") else ""} | set(alias[(alias.asset_id == r["asset_id"]) & (alias.alias_status == "ACTIVE")].alias)
        same -= {""}
        if mn not in same:
            why.append(f"測定の固有名詞が資産の正規名・別名と合致しない（別名として追加するなら alias に指定）: {mn}")
        if spec_names is not None and mn not in spec_names:
            why.append(f"測定で確認できた固有名詞にない: {mn}")
    if r.get("alias", "").strip():
        al = r["alias"].strip()
        al_n = al.replace(" ", "")
        other = master[(master.canonical_name_normalized == al_n) & (master.asset_id != r["asset_id"])]
        if len(other):
            why.append("別名が他資産の正規名と同一")
        ex = alias[(alias.alias == al) & (alias.alias_status == "ACTIVE")]
        if len(ex[ex.asset_id != r["asset_id"]]):
            why.append("別名が既に別の資産へ紐づいている")
        if ma.shape[0] == 1 and ma.iloc[0].asset_status != "ACTIVE":
            why.append("閉鎖・未検証の資産への別名は不可")
    rt = r.get("relation_type_to", "SELF_RESOURCE").strip() or "SELF_RESOURCE"
    if rt != "SELF_RESOURCE":
        why.append(f"関係の訂正先は SELF_RESOURCE のみ対応: {rt}")
    old = rel[(rel.asset_id == r["asset_id"]) & (rel.municipality_id.map(bare) == bare(r["municipality_id"])) & (rel.relation_status == "ACTIVE")]
    bad = old[~old.relation_type.isin(["REGIONAL_CONTEXT", "SELF_RESOURCE"])]
    if len(bad):
        why.append(f"既存の有効な関係が訂正対象外: {sorted(set(bad.relation_type))}")
    return why


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-root", required=True, help="現行パッケージ一式（読み取りのみ）")
    ap.add_argument("--spec-file", required=True)
    ap.add_argument("--measured-names", nargs="*", default=[], help="測定の固有名詞を含むCSV（列 candidate_text / resource_text / canonical_resource_name）。未指定なら照合しない（正式実行では必須）")
    ap.add_argument("--candidates-file", default=None, help="別名追加の影響確認用: 出現候補CSV（列 candidate_name）")
    ap.add_argument("--stage-root", required=True, help="存在しない新規フォルダ")
    ap.add_argument("--version", required=True, help="次版の版番号（例 1.5.52）。明示指定")
    ap.add_argument("--now", required=True, help="実行日時（再現性のため明示。例 2026-11-14T12:00:00+09:00）")
    ap.add_argument("--allow-no-measured", action="store_true", help="試験用: 測定の固有名詞の照合を省略する（正式実行では使わない）")
    ap.add_argument("--strict", action="store_true", help="1行でも不合格なら何も出力せず停止")
    a = ap.parse_args()

    base = Path(a.baseline_root)
    stage = Path(a.stage_root)
    if base.resolve() in stage.resolve().parents or stage.resolve() == base.resolve():
        raise Stop("stage-root が baseline の中にある")
    if not a.measured_names and not a.allow_no_measured:
        raise Stop("--measured-names が必須（測定の固有名詞との照合。試験時のみ --allow-no-measured で省略可）")
    if stage.exists():
        raise Stop(f"stage-root が既に存在する: {stage}")
    import re

    def pick(pat):
        c = sorted(base.glob(pat))
        if not c:
            raise Stop(f"baseline に {pat} が無い")
        vk = lambda p: [int(x) for x in re.findall(r"\d+", re.sub(r"^[^_]*", "", p.stem.split("_formal_slots")[0]))] or [0]
        c.sort(key=vk)
        if len(c) > 1 and vk(c[-1]) == vk(c[-2]):
            raise Stop(f"{pat} の最新版が一意に決まらない: {[x.name for x in c[-2:]]}")
        return c[-1]
    f = {"master": pick("common_tourism_asset_master_v*.csv"), "alias": pick("common_tourism_asset_alias_v*.csv"),
         "rel": pick("common_asset_municipality_relation_v*.csv"), "slots": pick("diagnostic_selector_v*_formal_slots_*.csv")}
    before = {k: sha(p) for k, p in f.items()}
    master, alias, rel, slots = (rd(f[k]) for k in ("master", "alias", "rel", "slots"))
    mnames = dict(zip(slots.municipality_id, slots.municipality_name))
    spec = rd(Path(a.spec_file))
    miss = [c for c in REQUIRED if c not in spec.columns]
    if miss:
        raise Stop(f"追記指定CSVに列が無い: {miss}")
    for c in OPTIONAL:
        if c not in spec.columns:
            spec[c] = ""

    names = None
    if a.measured_names:
        names = set()
        for p in a.measured_names:
            d = rd(Path(p))
            for c in ("candidate_text", "resource_text", "canonical_resource_name", "candidate_name"):
                if c in d.columns:
                    names |= set(d[c])

    ok_rows, unadopted = [], []
    seen = set()
    free = {m: int((g.common_asset_id == "").sum()) for m, g in slots.groupby("municipality_id")}
    have = {m: set(g.common_asset_id) for m, g in slots.groupby("municipality_id")}
    for _, r in spec.iterrows():
        why = check_row(r, master, alias, rel, names, mnames)
        key = (r["municipality_id"], r["asset_id"])
        if key in seen:
            why.append("指定CSV内で重複")
        seen.add(key)
        m_ = pre(r["municipality_id"])
        if not why and r["asset_id"] not in have.get(m_, set()):
            if free.get(m_, 0) <= 0:
                why.append("空スロットが無い（並べ替えモードは未対応）")
            else:
                free[m_] -= 1
        (unadopted if why else ok_rows).append({**r.to_dict(), "reasons": "；".join(why)} if why else r.to_dict())
    if a.strict and unadopted:
        raise Stop("不合格の行がある（--strict）: " + json.dumps([(u["municipality_id"], u["asset_id"], u["reasons"]) for u in unadopted], ensure_ascii=False))

    # ---- 適用 ----
    rel2, alias2, slots2 = rel.copy(), alias.copy(), slots.copy()
    diff = []
    now = a.now
    for r in ok_rows:
        m, aid = pre(r["municipality_id"]), r["asset_id"]
        eid = "EVID_APPEND_" + hashlib.sha1(f"{m}|{aid}|{r['audit_ref']}".encode()).hexdigest()[:16].upper()
        # (1) 関係の訂正
        cur = rel2[(rel2.asset_id == aid) & (rel2.municipality_id.map(bare) == bare(m)) & (rel2.relation_status == "ACTIVE")]
        if len(cur) and (cur.relation_type == "SELF_RESOURCE").any():
            pass  # 既に有効なSELF_RESOURCE
        else:
            idx = cur.index.tolist()
            mid_fmt = cur.municipality_id.iloc[0] if len(cur) else bare(m)
            for i in idx:
                rel2.loc[i, "relation_status"] = "SUPERSEDED"
                old_notes = rel2.loc[i, "notes"]
                rel2.loc[i, "notes"] = old_notes + f" | SUPERSEDED_BY={eid}"
                diff.append(["relation", m, aid, "relation_status(旧行)", "ACTIVE", "SUPERSEDED", f"旧行 relation_type={rel2.loc[i,'relation_type']}"])
                diff.append(["relation", m, aid, "notes(旧行)", old_notes, rel2.loc[i, "notes"], ""])
            new = {c: "" for c in rel2.columns}
            new.update(asset_id=aid, municipality_id=mid_fmt, relation_type="SELF_RESOURCE", verification_status="VERIFIED", is_primary="TRUE",
                       evidence_id=eid, relation_status="ACTIVE", original_asset_id=aid, original_relation_type="SELF_RESOURCE", updated_at=now,
                       notes=f"AUDITED_APPEND | audit={r['audit_ref']} | president={r['president_confirmation_ref']} | address={r['address_original']} | url={r['official_evidence_url']}")
            rel2 = pd.concat([rel2, pd.DataFrame([new])], ignore_index=True)
            diff.append(["relation", m, aid, "(新行)", "", f"SELF_RESOURCE/ACTIVE municipality_id={mid_fmt}", eid])
        # (2) 別名
        al = r["alias"].strip()
        if al:
            new = {c: "" for c in alias2.columns}
            new.update(asset_id=aid, alias=al, alias_scope="MUNICIPALITY", municipality_id=pre(m), context_rule="resolved_single_canonical",
                       verification_status="VERIFIED", source="AIV_RESOURCE_APPEND_TOOL", alias_status="ACTIVE", original_asset_id=aid,
                       original_alias_scope="MUNICIPALITY", created_at=now, updated_at=now,
                       notes=f"AUDITED_APPEND | audit={r['audit_ref']} | president={r['president_confirmation_ref']} | same facility confirmed")
            alias2 = pd.concat([alias2, pd.DataFrame([new])], ignore_index=True)
            diff.append(["alias", m, aid, "(新行)", "", f"{al} municipality_id={pre(m)} scope=MUNICIPALITY", ""])
        # (3) 空スロット充填
        cur_slots = slots2[slots2.municipality_id == m]
        if (cur_slots.common_asset_id == aid).any():
            continue
        empty = cur_slots[cur_slots.common_asset_id == ""].sort_values("display_slot", key=lambda s: s.astype(int))
        if empty.empty:
            raise Stop("内部エラー: 事前検査を通ったのに空スロットが無い")
        i = empty.index[0]
        ma = master[master.asset_id == aid].iloc[0]
        old_row = slots2.loc[i].to_dict()
        if r["evidence_kind"].strip() == "APA_REASON":
            tier, ns, apa_info = "APA_RESOURCE", "apa.reason", "APA_REASON_EVIDENCE_REVIEW"
        else:
            tier = r.get("source_tier", "").strip()
            if tier not in ("APPEARANCE_RANK_1_3", "APPEARANCE_RANK_4_5"):
                raise Stop("evidence_kind が APPEARANCE_CANDIDATE の行は source_tier（APPEARANCE_RANK_1_3 / APPEARANCE_RANK_4_5）の指定が必要")
            ns, apa_info = "appearance.candidate", ""
        slots2.loc[i, ["common_asset_id", "canonical_name", "source_tier", "source_namespace", "source_record_id", "appearance_candidate_rank",
                       "apa_source_information", "dedup_reason", "promotion_reason", "resource_scope", "relation_type", "relation_status",
                       "relation_evidence_id", "verification_status", "asset_status"]] = [
            aid, ma.canonical_name, tier, ns, r["source_record_ids"], "", apa_info,
            "UNIQUE_COMMON_ID", "MEASUREMENT_BACKED_SAFE_FILL", "LOCAL", "SELF_RESOURCE", "ACTIVE", eid, "VERIFIED", "ACTIVE"]
        for c in SLOT_COLS:
            if str(old_row[c]) != str(slots2.loc[i, c]):
                diff.append(["slot", m, aid, f"display_slot={slots2.loc[i,'display_slot']}:{c}", old_row[c], slots2.loc[i, c], eid])

    # ---- 回帰検査 ----
    checks = {}
    checks["municipalities"] = slots2.municipality_id.nunique()
    checks["slot_rows"] = len(slots2)
    checks["dup_asset_within_municipality"] = int(slots2[slots2.common_asset_id != ""].duplicated(["municipality_id", "common_asset_id"]).sum())
    changed = slots2.compare(slots) if len(slots2) == len(slots) else None
    changed_mun = sorted(set(slots2.loc[changed.index, "municipality_id"])) if changed is not None and len(changed) else []
    checks["changed_municipalities"] = changed_mun
    checks["changed_outside_spec"] = [x for x in changed_mun if x not in {pre(r["municipality_id"]) for r in ok_rows}]
    nonblank = slots2[slots2.common_asset_id != ""]
    checks["non_self_slots"] = int((nonblank.relation_type != "SELF_RESOURCE").sum())
    checks["baseline_non_self_slots"] = int((slots[slots.common_asset_id != ""].relation_type != "SELF_RESOURCE").sum())
    spec_pairs = {(r["asset_id"], bare(r["municipality_id"])) for r in ok_rows}
    ch = rel2.iloc[: len(rel)].compare(rel) if len(rel2) >= len(rel) else None
    ch_idx = list(ch.index) if ch is not None and len(ch) else []
    checks["relation_changed_outside_spec"] = [i for i in ch_idx if (rel.loc[i, "asset_id"], bare(rel.loc[i, "municipality_id"])) not in spec_pairs]
    checks["relation_changed_cols_only_status_notes"] = bool(ch is None or len(ch) == 0 or set(c[0] for c in ch.columns) <= {"relation_status", "notes"})
    checks["alias_old_rows_identical"] = bool(alias2.iloc[: len(alias)].equals(alias))
    checks["old_rows_kept_rel"] = bool(rel.merge(rel2, how="left", on=["asset_id", "municipality_id", "relation_type", "evidence_id"], indicator=True)["_merge"].eq("both").all())
    checks["active_self_per_asset_muni_dup"] = int(rel2[(rel2.relation_status == "ACTIVE") & (rel2.relation_type == "SELF_RESOURCE")].duplicated(["asset_id", "municipality_id"]).sum())
    after_same = {k: sha(p) for k, p in f.items()}
    checks["baseline_unchanged"] = after_same == before
    passed = (checks["dup_asset_within_municipality"] == 0 and not checks["changed_outside_spec"] and checks["old_rows_kept_rel"]
              and checks["baseline_unchanged"] and checks["active_self_per_asset_muni_dup"] == 0
              and not checks["relation_changed_outside_spec"] and checks["relation_changed_cols_only_status_notes"] and checks["alias_old_rows_identical"]
              and checks["non_self_slots"] == checks["baseline_non_self_slots"])

    # ---- 別名の影響（新たに解決される既存行） ----
    impact = []
    if a.candidates_file:
        cd = rd(Path(a.candidates_file))
        col = "candidate_name" if "candidate_name" in cd.columns else cd.columns[0]
        for r in ok_rows:
            al = r["alias"].strip()
            if al:
                hit = cd[cd[col] == al]
                for _, h in hit.iterrows():
                    impact.append({"alias": al, "asset_id": r["asset_id"], **{k: h.get(k, "") for k in ("candidate_row_id", "question_id", "category_id", "scope", "candidate_rank")}})

    # ---- 出力 ----
    stage.mkdir(parents=True)
    ver = a.version.replace(".", "_")

    def wr(name, df):
        df.to_csv(stage / name, index=False, encoding="utf-8-sig", lineterminator="\n")

    wr(f"common_asset_municipality_relation_{ver}_stage.csv", rel2)
    wr(f"common_tourism_asset_alias_{ver}_stage.csv", alias2)
    wr(f"diagnostic_selector_v{ver}_formal_slots_stage.csv", slots2[SLOT_COLS])
    with (stage / "expected_diff.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh); w.writerow(["file", "municipality_id", "asset_id", "field", "before", "after", "note"]); w.writerows(diff)
    wr("unadopted.csv", pd.DataFrame(unadopted) if unadopted else pd.DataFrame(columns=REQUIRED + ["reasons"]))
    wr("alias_impact.csv", pd.DataFrame(impact) if impact else pd.DataFrame(columns=["alias", "asset_id", "candidate_row_id"]))
    summary = {"version": a.version, "now": a.now, "status": "PASS" if passed else "FAIL", "checks": checks, "adopted": len(ok_rows),
               "unadopted": len(unadopted), "diff_rows": len(diff), "alias_impact_rows": len(impact), "baseline_sha256": before,
               "note": "stageのみ。正式ポインタ・Gate・PPTXは未変更。反映は社長確認②の後。"}
    (stage / "validation.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    man = {p.name: sha(p) for p in sorted(stage.iterdir()) if p.name != "manifest.json"}
    (stage / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("status", "adopted", "unadopted", "diff_rows", "alias_impact_rows")} | {"stage": str(stage)}, ensure_ascii=False))
    if not passed:
        sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except Stop as e:
        print("STOP:", e)
        sys.exit(1)
