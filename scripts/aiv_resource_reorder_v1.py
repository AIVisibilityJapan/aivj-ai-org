#!/usr/bin/env python3
"""資源 並べ替え・改名ツール（stage専用）。仕様: 福岡市 並べ替え・改名モード 仕様案（2026-11-19、社長確認済み）

既存の aiv_resource_append_v2.py は変更しない。このツールは、1自治体の Top3 枠の入れ替え、既存資産の改名
（資産IDは維持・旧名は別名へ）、新規資産・別名の追加を、stage にだけ書き出す。

- 入力（baseline）は読み取りのみ。実行前後の SHA256 を比較し、変わっていれば失敗。
- 出力は --stage-root（存在しない新規フォルダ）だけ。正式ポインタ・Gate・PPTX には触れない。
- 差分を expected_diff.csv に全件出す。人の承認なしに stage を次へ進めない（このツールは承認を判断しない）。
- 対象自治体以外の変更が1行でもあれば FAIL。
- 承認番号は指定CSVの列に人が書く。このツールは採番しない。

指定CSV（--spec-file）の列:
  op                  SLOT / RENAME / ALIAS / NEWASSET
  municipality_id     対象自治体（全行で同一であること）
  asset_id            既存の資産ID。新規は NEW:<正規名>（決定的採番）
  name                RENAME: 新しい正規名 / NEWASSET: 正規名 / ALIAS: 追加する別名
  slot                SLOT: 1〜（最終状態を全枠指定する）
  source_tier         SLOT: APPEARANCE_RANK_1_3 / APA_RESOURCE / APPEARANCE_RANK_4_5
  source_record_ids   SLOT: 根拠の記録ID（新しい枠のとき必須）
  new_resource_type / new_resource_subtype   NEWASSET: 種別（必須）
  address_original, address_municipality, official_evidence_url, evidence_kind(APA_REASON/APPEARANCE_CANDIDATE)
                      NEWASSET: 必須（実在と所在の根拠）
  audit_ref, president_confirmation_ref   全行で必須（人が記入。空なら不採用）
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

import pandas as pd

SLOT_COLS = ["municipality_id", "municipality_name", "display_slot", "common_asset_id", "canonical_name", "source_tier", "source_namespace",
             "source_record_id", "appearance_candidate_rank", "apa_source_information", "dedup_reason", "promotion_reason", "resource_scope",
             "relation_type", "relation_status", "relation_evidence_id", "verification_status", "asset_status"]
TIERS = ("APPEARANCE_RANK_1_3", "APA_RESOURCE", "APPEARANCE_RANK_4_5")
COMMON_REQ = ["op", "municipality_id", "asset_id", "audit_ref", "president_confirmation_ref"]
NEW_REQ = ["name", "new_resource_type", "new_resource_subtype", "address_original", "address_municipality", "official_evidence_url", "evidence_kind"]


class Stop(Exception):
    pass


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def rd(p: Path) -> pd.DataFrame:
    return pd.read_csv(p, encoding="utf-8-sig", dtype=str).fillna("")


def bare(m: str) -> str:
    return m[5:] if m.startswith("MUNI_") else m


def pre(m: str) -> str:
    return m if m.startswith("MUNI_") else "MUNI_" + m


def norm(s: str) -> str:
    return s.replace(" ", "").replace("　", "")


def new_asset_id(mid: str, name: str) -> str:
    # aiv_resource_append_v2.py と同じ決定的採番
    return "AIV_COMMON_ASSET_PREFLIGHT_" + hashlib.sha256(f"{pre(mid)}|{name.strip()}".encode("utf-8")).hexdigest()[:20].upper()


def pick(base: Path, pat: str) -> Path:
    c = sorted(base.glob(pat))
    if not c:
        raise Stop(f"baseline に {pat} が無い")
    vk = lambda p: [int(x) for x in re.findall(r"\d+", re.sub(r"^[^_]*", "", p.stem.split("_formal_slots")[0]))] or [0]
    c.sort(key=vk)
    if len(c) > 1 and vk(c[-1]) == vk(c[-2]):
        raise Stop(f"{pat} の最新版が一意に決まらない: {[x.name for x in c[-2:]]}")
    return c[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-root", required=True)
    ap.add_argument("--spec-file", required=True)
    ap.add_argument("--measured-names", nargs="*", default=[], help="測定の固有名詞を含むCSV（列 candidate_name 等）。NEWASSET の名称照合に使う")
    ap.add_argument("--allow-no-measured", action="store_true", help="試験用（正式実行では使わない）")
    ap.add_argument("--stage-root", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--now", required=True)
    a = ap.parse_args()

    base, stage = Path(a.baseline_root), Path(a.stage_root)
    if base.resolve() in stage.resolve().parents or stage.resolve() == base.resolve():
        raise Stop("stage-root が baseline の中にある")
    if stage.exists():
        raise Stop(f"stage-root が既に存在する: {stage}")
    if not a.measured_names and not a.allow_no_measured:
        raise Stop("--measured-names が必須（試験時のみ --allow-no-measured）")

    f = {"master": pick(base, "common_tourism_asset_master_v*.csv"), "alias": pick(base, "common_tourism_asset_alias_v*.csv"),
         "rel": pick(base, "common_asset_municipality_relation_v*.csv"), "slots": pick(base, "diagnostic_selector_v*_formal_slots_*.csv")}
    before = {k: sha(p) for k, p in f.items()}
    master, alias, rel, slots = (rd(f[k]) for k in ("master", "alias", "rel", "slots"))
    mnames = dict(zip(slots.municipality_id, slots.municipality_name))

    spec = rd(Path(a.spec_file))
    for c in COMMON_REQ:
        if c not in spec.columns:
            raise Stop(f"指定CSVに列が無い: {c}")
    for c in set(NEW_REQ + ["slot", "source_tier", "source_record_ids"]):
        if c not in spec.columns:
            spec[c] = ""
    muns = {pre(m) for m in spec.municipality_id}
    if len(muns) != 1:
        raise Stop(f"指定CSVの自治体は1つだけ（このツールは1自治体専用）: {sorted(muns)}")
    mun = muns.pop()
    if mun not in mnames:
        raise Stop(f"スロット表に存在しない自治体: {mun}")
    for i, r in spec.iterrows():
        for c in ("audit_ref", "president_confirmation_ref"):
            if not r[c].strip():
                raise Stop(f"{c} が空（人が記入する。このツールは採番しない）: 行{i + 2}")
        if r["op"] not in ("SLOT", "RENAME", "ALIAS", "NEWASSET"):
            raise Stop(f"op が不正: {r['op']}")

    names = None
    if a.measured_names:
        names = set()
        for p in a.measured_names:
            d = rd(Path(p))
            for c in ("candidate_text", "resource_text", "canonical_resource_name", "candidate_name"):
                if c in d.columns:
                    names |= set(d[c])

    def resolve(aid: str, name_hint: str = "") -> str:
        return new_asset_id(mun, aid[4:]) if aid.upper().startswith("NEW:") else aid

    problems = []
    now = a.now
    master2, alias2, rel2, slots2 = master.copy(), alias.copy(), rel.copy(), slots.copy()
    diff = []
    evid = lambda aid, ref: "EVID_REORDER_" + hashlib.sha1(f"{mun}|{aid}|{ref}".encode()).hexdigest()[:16].upper()

    # ---- 1. NEWASSET ----
    for _, r in spec[spec.op == "NEWASSET"].iterrows():
        nm = r["name"].strip()
        aid = resolve(r["asset_id"])
        if not r["asset_id"].upper().startswith("NEW:") or r["asset_id"][4:].strip() != nm:
            problems.append(f"NEWASSET の asset_id は NEW:<name> で name と一致させる: {r['asset_id']}")
            continue
        miss = [c for c in NEW_REQ if not r[c].strip()]
        if miss:
            problems.append(f"NEWASSET の必須項目が空 {nm}: {miss}")
            continue
        if r["address_municipality"].strip() != mnames[mun]:
            problems.append(f"{nm}: 住所の所在自治体が対象と一致しない: {r['address_municipality']} / {mnames[mun]}")
            continue
        if r["evidence_kind"].strip() not in ("APA_REASON", "APPEARANCE_CANDIDATE"):
            problems.append(f"{nm}: evidence_kind が不正")
            continue
        if names is not None and nm not in names:
            problems.append(f"{nm}: 測定で確認できた固有名詞にない")
            continue
        if (master2.asset_id == aid).any() or (master2.canonical_name_normalized == norm(nm)).any():
            problems.append(f"{nm}: 同じIDまたは正規名の資産が既にある")
            continue
        if ((alias2.alias == nm) & (alias2.alias_status == "ACTIVE")).any():
            problems.append(f"{nm}: 同じ表記の別名が既にある")
            continue
        eid = evid(aid, r["audit_ref"])
        row = {c: "" for c in master2.columns}
        row.update(asset_id=aid, canonical_name=nm, canonical_name_normalized=norm(nm), resource_type=r["new_resource_type"].strip(),
                   resource_subtype=r["new_resource_subtype"].strip(), primary_municipality_id=mun, verified_municipality_ids=mun,
                   verification_status="VERIFIED", asset_status="ACTIVE", first_source="AIV_RESOURCE_REORDER_TOOL_NEW_ASSET",
                   first_source_asset_id=aid, first_seen_measurement="APA_V1" if r["evidence_kind"].strip() == "APA_REASON" else "APPEARANCE",
                   last_verified_at=now[:10], merge_basis="MEASUREMENT_ORIGINAL_TEXT_AND_OFFICIAL_EVIDENCE", merge_confidence="HIGH",
                   created_at=now, updated_at=now,
                   notes=f"AUDITED_NEW_ASSET | audit={r['audit_ref']} | president={r['president_confirmation_ref']} | address={r['address_original']} | url={r['official_evidence_url']}")
        master2 = pd.concat([master2, pd.DataFrame([row])], ignore_index=True)
        diff.append(["master", mun, aid, "(新行)", "", f"{nm} type={row['resource_type']} subtype={row['resource_subtype']} primary={mun}", eid])
        rrow = {c: "" for c in rel2.columns}
        rrow.update(asset_id=aid, municipality_id=mun, relation_type="SELF_RESOURCE", verification_status="VERIFIED", is_primary="TRUE",
                    evidence_id=eid, relation_status="ACTIVE", original_asset_id=aid, original_relation_type="SELF_RESOURCE", updated_at=now,
                    notes=f"AUDITED_NEW_ASSET | audit={r['audit_ref']} | president={r['president_confirmation_ref']} | address={r['address_original']} | url={r['official_evidence_url']}")
        rel2 = pd.concat([rel2, pd.DataFrame([rrow])], ignore_index=True)
        diff.append(["relation", mun, aid, "(新行)", "", f"SELF_RESOURCE/ACTIVE municipality_id={mun}", eid])

    # ---- 2. RENAME（ID維持・旧名を別名へ）----
    renamed = {}
    for _, r in spec[spec.op == "RENAME"].iterrows():
        aid, new = r["asset_id"].strip(), r["name"].strip()
        m = master2[master2.asset_id == aid]
        if len(m) != 1:
            problems.append(f"RENAME: 資産IDがマスターに1件でない: {aid}")
            continue
        x = m.iloc[0]
        if x.asset_status != "ACTIVE" or x.verification_status != "VERIFIED":
            problems.append(f"RENAME: ACTIVE/VERIFIED でない: {aid}")
            continue
        vm = {pre(v) for v in x.verified_municipality_ids.replace("|", ";").split(";") if v} | {pre(x.primary_municipality_id)}
        if vm != {mun}:
            problems.append(f"RENAME: 他の自治体にも属する資産は対象外（影響が広い）: {aid} {sorted(vm)}")
            continue
        if not new or norm(new) == x.canonical_name_normalized:
            problems.append(f"RENAME: 新しい名称が空または同一: {aid}")
            continue
        if ((master2.canonical_name_normalized == norm(new)) & (master2.asset_id != aid)).any():
            problems.append(f"RENAME: 新しい名称が他の資産の正規名と同一: {new}")
            continue
        if ((alias2.alias == new) & (alias2.alias_status == "ACTIVE") & (alias2.asset_id != aid)).any():
            problems.append(f"RENAME: 新しい名称が他の資産の有効な別名: {new}")
            continue
        other = slots2[(slots2.common_asset_id == aid) & (slots2.municipality_id != mun)]
        if len(other):
            problems.append(f"RENAME: 他の自治体の枠にこの資産がある: {sorted(set(other.municipality_id))}")
            continue
        old = x.canonical_name
        i = m.index[0]
        master2.loc[i, "canonical_name"] = new
        master2.loc[i, "canonical_name_normalized"] = norm(new)
        master2.loc[i, "updated_at"] = now
        master2.loc[i, "notes"] = x.notes + f" | RENAMED_FROM={old} | audit={r['audit_ref']} | president={r['president_confirmation_ref']}"
        diff.append(["master", mun, aid, "canonical_name", old, new, f"audit={r['audit_ref']}"])
        diff.append(["master", mun, aid, "canonical_name_normalized", x.canonical_name_normalized, norm(new), ""])
        diff.append(["master", mun, aid, "notes", x.notes, master2.loc[i, "notes"], ""])
        renamed[aid] = (old, new)
        if not ((alias2.alias == old) & (alias2.asset_id == aid) & (alias2.alias_status == "ACTIVE")).any():
            row = {c: "" for c in alias2.columns}
            row.update(asset_id=aid, alias=old, alias_scope="MUNICIPALITY", municipality_id=mun, context_rule="resolved_single_canonical",
                       verification_status="VERIFIED", source="AIV_RESOURCE_REORDER_TOOL", alias_status="ACTIVE", original_asset_id=aid,
                       original_alias_scope="MUNICIPALITY", created_at=now, updated_at=now,
                       notes=f"RENAME_OLD_NAME | audit={r['audit_ref']} | president={r['president_confirmation_ref']}")
            alias2 = pd.concat([alias2, pd.DataFrame([row])], ignore_index=True)
            diff.append(["alias", mun, aid, "(新行)", "", f"{old} municipality_id={mun} scope=MUNICIPALITY（改名前の名称）", ""])

    # ---- 3. ALIAS ----
    for _, r in spec[spec.op == "ALIAS"].iterrows():
        aid, al = resolve(r["asset_id"]), r["name"].strip()
        ma = master2[master2.asset_id == aid]
        if len(ma) != 1:
            problems.append(f"ALIAS: 資産IDがマスターに1件でない: {aid}")
            continue
        if ma.iloc[0].asset_status != "ACTIVE":
            problems.append(f"ALIAS: ACTIVE でない資産: {aid}")
            continue
        if not al or norm(al) == ma.iloc[0].canonical_name_normalized:
            problems.append(f"ALIAS: 別名が空または正規名と同一: {al}")
            continue
        if ((master2.canonical_name_normalized == norm(al)) & (master2.asset_id != aid)).any():
            problems.append(f"ALIAS: 別名が他の資産の正規名と同一: {al}")
            continue
        ex = alias2[(alias2.alias == al) & (alias2.alias_status == "ACTIVE")]
        if len(ex[ex.asset_id != aid]):
            problems.append(f"ALIAS: 別名が既に別の資産へ紐づいている: {al}")
            continue
        if len(ex[ex.asset_id == aid]):
            continue
        row = {c: "" for c in alias2.columns}
        row.update(asset_id=aid, alias=al, alias_scope="MUNICIPALITY", municipality_id=mun, context_rule="resolved_single_canonical",
                   verification_status="VERIFIED", source="AIV_RESOURCE_REORDER_TOOL", alias_status="ACTIVE", original_asset_id=aid,
                   original_alias_scope="MUNICIPALITY", created_at=now, updated_at=now,
                   notes=f"AUDITED_APPEND | audit={r['audit_ref']} | president={r['president_confirmation_ref']}")
        alias2 = pd.concat([alias2, pd.DataFrame([row])], ignore_index=True)
        diff.append(["alias", mun, aid, "(新行)", "", f"{al} municipality_id={mun} scope=MUNICIPALITY", ""])

    # ---- 4. SLOT（最終状態を全枠指定）----
    cur = slots[slots.municipality_id == mun].copy()
    cur["_n"] = cur.display_slot.astype(int)
    cur = cur.sort_values("_n")
    want = spec[spec.op == "SLOT"].copy()
    if len(want):
        try:
            want["_n"] = want.slot.astype(int)
        except ValueError:
            raise Stop("slot は整数で指定する")
        if sorted(want._n) != sorted(cur._n):
            problems.append(f"SLOT: 全枠を指定する（現行の枠 {sorted(cur._n)} / 指定 {sorted(want._n)}）")
        if want.asset_id.map(resolve).duplicated().any():
            problems.append("SLOT: 同じ資産を複数の枠に指定している")
        for _, r in want.sort_values("_n").iterrows():
            aid = resolve(r["asset_id"])
            ma = master2[master2.asset_id == aid]
            if len(ma) != 1:
                problems.append(f"SLOT {r['_n']}: 資産IDがマスターに1件でない: {aid}")
                continue
            x = ma.iloc[0]
            if x.asset_status != "ACTIVE" or x.verification_status != "VERIFIED":
                problems.append(f"SLOT {r['_n']}: ACTIVE/VERIFIED でない: {aid}")
                continue
            act = rel2[(rel2.asset_id == aid) & (rel2.municipality_id.map(bare) == bare(mun)) & (rel2.relation_status == "ACTIVE")]
            if not (act.relation_type == "SELF_RESOURCE").any():
                problems.append(f"SLOT {r['_n']}: 対象自治体との有効な SELF_RESOURCE 関係が無い: {aid}")
                continue
            idx = cur[cur.common_asset_id == aid]
            n = int(r["_n"])
            slot_idx = slots2[(slots2.municipality_id == mun) & (slots2.display_slot == str(n))].index[0]
            if len(idx):
                row = idx.iloc[0].drop(labels=["_n"]).to_dict()
            else:
                if r["source_tier"].strip() not in TIERS:
                    problems.append(f"SLOT {n}: 新しく枠に入れる資産は source_tier の指定が必要: {aid}")
                    continue
                if not r["source_record_ids"].strip():
                    problems.append(f"SLOT {n}: 新しく枠に入れる資産は source_record_ids が必要: {aid}")
                    continue
                tier = r["source_tier"].strip()
                ns = "apa.reason" if tier == "APA_RESOURCE" else "appearance.candidate"
                row = {c: "" for c in SLOT_COLS}
                row.update(municipality_id=mun, municipality_name=mnames[mun], common_asset_id=aid, canonical_name=x.canonical_name,
                           source_tier=tier, source_namespace=ns, source_record_id=r["source_record_ids"].strip(),
                           apa_source_information="APA_REASON_EVIDENCE_REVIEW" if tier == "APA_RESOURCE" else "",
                           dedup_reason="UNIQUE_COMMON_ID", promotion_reason="MEASUREMENT_BACKED_REORDER", resource_scope="LOCAL",
                           relation_type="SELF_RESOURCE", relation_status="ACTIVE", relation_evidence_id=act.iloc[0].evidence_id,
                           verification_status="VERIFIED", asset_status="ACTIVE")
            row["display_slot"] = str(n)
            row["canonical_name"] = x.canonical_name  # 改名を反映
            old_row = slots2.loc[slot_idx].to_dict()
            for c in SLOT_COLS:
                slots2.loc[slot_idx, c] = row[c]
                if str(old_row[c]) != str(row[c]):
                    diff.append(["slot", mun, aid, f"display_slot={n}:{c}", old_row[c], row[c], f"audit={r['audit_ref']}"])
    # 枠にない資産の改名は、他の枠に影響しないことを回帰で確認する

    # ---- 回帰検査 ----
    chk = {}
    chk["municipalities"] = int(slots2.municipality_id.nunique())
    chk["slot_rows"] = len(slots2)
    chk["slot_rows_same_as_baseline"] = len(slots2) == len(slots)
    chk["dup_asset_within_municipality"] = int(slots2[slots2.common_asset_id != ""].duplicated(["municipality_id", "common_asset_id"]).sum())
    ch = slots2[SLOT_COLS].compare(slots[SLOT_COLS]) if chk["slot_rows_same_as_baseline"] else None
    chm = sorted(set(slots2.loc[ch.index, "municipality_id"])) if ch is not None and len(ch) else []
    chk["changed_municipalities"] = chm
    chk["changed_outside_target"] = [m for m in chm if m != mun]
    nb = slots2[slots2.common_asset_id != ""]
    chk["non_self_slots"] = int((nb.relation_type != "SELF_RESOURCE").sum())
    chk["baseline_non_self_slots"] = int((slots[slots.common_asset_id != ""].relation_type != "SELF_RESOURCE").sum())
    tier_rank = {t: i for i, t in enumerate(TIERS)}
    t = slots2[slots2.municipality_id == mun].assign(_n=lambda d: d.display_slot.astype(int)).sort_values("_n")
    tt = [tier_rank[x] for x in t.source_tier if x in tier_rank]
    chk["target_tier_order_monotone"] = tt == sorted(tt)
    chk["target_slots_filled"] = int((t.common_asset_id != "").sum())
    chk["master_old_rows_changed_only_rename"] = bool(
        master2.iloc[: len(master)].drop(columns=["canonical_name", "canonical_name_normalized", "updated_at", "notes"]).equals(
            master.drop(columns=["canonical_name", "canonical_name_normalized", "updated_at", "notes"]))
        and set(master2.iloc[: len(master)].loc[~master2.iloc[: len(master)].eq(master).all(axis=1), "asset_id"]) <= set(renamed))
    chk["master_dup_ids"] = int(master2.asset_id.duplicated().sum())
    chk["master_dup_names"] = int(master2.canonical_name_normalized.duplicated().sum() - master.canonical_name_normalized.duplicated().sum())
    chk["alias_old_rows_identical"] = bool(alias2.iloc[: len(alias)].equals(alias))
    chk["relation_old_rows_identical"] = bool(rel2.iloc[: len(rel)].equals(rel))
    chk["alias_active_conflicts"] = int(alias2[alias2.alias_status == "ACTIVE"].duplicated(["alias", "municipality_id"]).sum())
    chk["problems"] = len(problems)
    chk["baseline_unchanged"] = {k: sha(p) for k, p in f.items()} == before
    passed = (not problems and chk["dup_asset_within_municipality"] == 0 and not chk["changed_outside_target"]
              and chk["slot_rows_same_as_baseline"] and chk["non_self_slots"] == chk["baseline_non_self_slots"]
              and chk["target_tier_order_monotone"] and chk["master_old_rows_changed_only_rename"] and chk["master_dup_ids"] == 0
              and chk["master_dup_names"] == 0 and chk["alias_old_rows_identical"] and chk["relation_old_rows_identical"]
              and chk["baseline_unchanged"])

    # 改名の影響: canonical_name（旧名）を参照している他の自治体の枠・出力
    impact = []
    for aid, (old, new) in renamed.items():
        for _, s in slots[slots.canonical_name == old].iterrows():
            impact.append({"asset_id": aid, "old_name": old, "new_name": new, "municipality_id": s.municipality_id, "display_slot": s.display_slot})

    stage.mkdir(parents=True)
    ver = a.version.replace(".", "_")

    def wr(name, df):
        df.to_csv(stage / name, index=False, encoding="utf-8-sig", lineterminator="\n")

    wr(f"common_tourism_asset_master_{ver}_stage.csv", master2)
    wr(f"common_asset_municipality_relation_{ver}_stage.csv", rel2)
    wr(f"common_tourism_asset_alias_{ver}_stage.csv", alias2)
    wr(f"diagnostic_selector_v{ver}_formal_slots_stage.csv", slots2[SLOT_COLS])
    with (stage / "expected_diff.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "municipality_id", "asset_id", "field", "before", "after", "note"])
        w.writerows(diff)
    wr("unadopted.csv", pd.DataFrame({"reasons": problems}) if problems else pd.DataFrame(columns=["reasons"]))
    wr("rename_impact.csv", pd.DataFrame(impact) if impact else pd.DataFrame(columns=["asset_id", "old_name", "new_name", "municipality_id", "display_slot"]))
    summary = {"version": a.version, "now": a.now, "status": "PASS" if passed else "FAIL", "target": mun, "checks": chk, "problems": problems,
               "diff_rows": len(diff), "baseline_sha256": before,
               "note": "stageのみ。expected_diff.csv を人が全件確認し承認するまで次へ進まない。正式ポインタ・Gate・PPTXは未変更。"}
    (stage / "validation.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    man = {p.name: sha(p) for p in sorted(stage.iterdir()) if p.name != "manifest.json"}
    (stage / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "diff_rows": len(diff), "problems": problems, "stage": str(stage)}, ensure_ascii=False))
    print("STOP: expected_diff.csv の全件確認と承認が必要（このツールは承認を判断しない）")
    if not passed:
        sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except Stop as e:
        print("STOP:", e)
        sys.exit(1)
