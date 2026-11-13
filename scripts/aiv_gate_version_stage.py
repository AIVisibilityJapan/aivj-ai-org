import json, hashlib, re, shutil, sys, datetime
from pathlib import Path
# 使い方: python aiv_gate_version_stage.py <出力先(新規)> <status_stage_csv> <正式ルート(…\\AI Visibility)>
FR = Path(sys.argv[3])
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True)
G = "03_実行基盤・コード/03_診断レポート/現行レポート基盤/03_generated"
REL = {
 "status": "outputs/AIV_resource_preflight_gate_v1_1_9_ledger_review_20261114/sources/gate_municipality_status_v1_1_9.csv",
 "contract": "outputs/AIV_source_contract_v1_1_10_gate_status_20261114/02_gate_source_contract_v1_1_10.json",
 "config": f"{G}/config/resource_coverage_preflight_gate_v1_1_9_source_contract_v1_1_10.json",
 "runtime": f"{G}/scripts/aiv_resource_coverage_preflight_source_contract_v1_1_10.py",
 "launcher": f"{G}/scripts/aiv_generate_light_report_source_contract_guarded_v1_1_10.py",
 "pointer": f"{G}/config/resource_coverage_preflight_formal_current.json",
}
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def put(key, data):
    p = OUT / "formal_root_overlay" / REL[key]; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8")); return p
OLD = {
 "contract": FR/"outputs/AIV_source_contract_v1_1_9_alignment_20261101/02_gate_source_contract_v1_1_9.json",
 "config": FR/G/"config/resource_coverage_preflight_gate_v1_1_8_source_contract_v1_1_9.json",
 "runtime": FR/G/"scripts/aiv_resource_coverage_preflight_source_contract_v1_1_9.py",
 "launcher": FR/G/"scripts/aiv_generate_light_report_source_contract_guarded_v1_1_9.py",
 "pointer": FR/G/"config/resource_coverage_preflight_formal_current.json",
}
OLDSHA = {k: sha(v) for k, v in OLD.items()}
assert OLDSHA["contract"] == "ff4551b96d14b0a90743e646080a04e13f9f63b04c7d3ec847f84fc41ab0e18b"
# 1 status
st = put("status", Path(sys.argv[2]).read_bytes())
# 2 runtime adapter
s = OLD["runtime"].read_text(encoding="utf-8")
subs = [
 ("'resource_preflight':'1.1.8','appearance_formal'", "'resource_preflight':'1.1.9','appearance_formal'"),
 ("require(contract.get('source_contract_version')=='1.1.9','SOURCE_CONTRACT_VERSION_MISMATCH')", "require(contract.get('source_contract_version')=='1.1.10','SOURCE_CONTRACT_VERSION_MISMATCH')"),
 ("require(contract.get('gate_version')=='1.1.8','PREFLIGHT_VERSION_MISMATCH')", "require(contract.get('gate_version')=='1.1.9','PREFLIGHT_VERSION_MISMATCH')"),
 ("require(contract['previous_version']=='1.1.8' and contract['previous_contract_sha256']=='dc973eae1a891c18eba7f1eaeb4c367412c1f45d122a5f0351c47f3bc5550b16'",
  "require(contract['previous_version']=='1.1.9' and contract['previous_contract_sha256']=='ff4551b96d14b0a90743e646080a04e13f9f63b04c7d3ec847f84fc41ab0e18b'"),
 ("require(self.pointer.get('gate_version')=='1.1.8','PREFLIGHT_VERSION_MISMATCH')", "require(self.pointer.get('gate_version')=='1.1.9','PREFLIGHT_VERSION_MISMATCH')"),
 ("require(self.pointer.get('source_contract_version')=='1.1.9','SOURCE_CONTRACT_VERSION_MISMATCH')", "require(self.pointer.get('source_contract_version')=='1.1.10','SOURCE_CONTRACT_VERSION_MISMATCH')"),
 ("class ResourceCoveragePreflightSourceContractV119(", "class ResourceCoveragePreflightSourceContractV1110("),
 ("return ResourceCoveragePreflightSourceContractV119(pointer_path)", "return ResourceCoveragePreflightSourceContractV1110(pointer_path)"),
 ('"""Source-validation adapter9; Resource Preflight evaluation remains8.', '"""Source-validation adapter 1.1.10 (Gate 1.1.9: status rebuilt for ledger-reviewed municipalities); evaluation logic remains 1.1.8.'),
 ("AUDIT = Path(r'C:\\Users\\高木駿\\.codex\\visualizations\\2026\\10\\28\\01a1830d-d2be-7bd3-9ac7-f63117bb08d9\\aiv_source_contract_batch2_20261101')",
  "import os\nAUDIT = Path(os.environ.get('AIV_GATE_AUDIT_ROOT') or '/__AIV_GATE_AUDIT_ROOT_NOT_SET__')"),
 ("    CURRENT = Path(r'C:\\Users\\高木駿\\OneDrive - 株式会社シアンウォールズ\\ドキュメント\\999AI操作ファイル\\AI Visibility')",
  "    _root = os.environ.get('AIV_FORMAL_ROOT')\n    if not _root:\n        raise RuntimeError('AIV_FORMAL_ROOT_NOT_SET')\n    CURRENT = Path(_root)"),
]
for a, b in subs:
    if a not in s: print("MISSING", a[:70]); 
    s = s.replace(a, b)
assert "V119" not in s.replace("V1110", ""), [m.start() for m in re.finditer("V119", s)]
rt = put("runtime", s)
# 3 launcher
l = OLD["launcher"].read_text(encoding="utf-8")
l = l.replace("aiv_resource_coverage_preflight_source_contract_v1_1_9", "aiv_resource_coverage_preflight_source_contract_v1_1_10").replace("ResourceCoveragePreflightSourceContractV119", "ResourceCoveragePreflightSourceContractV1110")
l = l.replace("'gate_version':'1.1.8',\n        'source_contract_version':'1.1.9'", "'gate_version':'1.1.9',\n        'source_contract_version':'1.1.10'")
assert "V119" not in l.replace("V1110", "") and "'source_contract_version':'1.1.10'" in l
lc = put("launcher", l)
# 4 contract
c = json.loads(OLD["contract"].read_text(encoding="utf-8-sig"))
now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat()
c["source_contract_version"] = "1.1.10"; c["gate_version"] = "1.1.9"; c["generated_at"] = now; c["created_at"] = now
c["creation_reason"] = "Append-only Gate 1.1.9: gate_municipality_status rebuilt for municipalities whose resource candidates were reviewed via the review ledger (stage; see expected_diff). Evaluation logic unchanged (inherited from 1.1.8). No measurements, rankings or other source bytes changed."
c["previous_version"] = "1.1.9"; c["previous_contract_path"] = "outputs/AIV_source_contract_v1_1_9_alignment_20261101/02_gate_source_contract_v1_1_9.json"; c["previous_contract_sha256"] = OLDSHA["contract"]
c["version_assignment_evidence"] = "Source contract next unused patch after 1.1.9 is 1.1.10; Gate next patch after 1.1.8 is 1.1.9. Names confirmed by the president on 2026-11-14."
c["bound_versions"]["resource_preflight"] = "1.1.9"
for src in c["sources"]:
    if src["logical_source_name"] == "gate_municipality_status":
        src.update(path_relative_to_formal_root=REL["status"], resolved_path_at_build="(stage) " + REL["status"], version="1.1.9",
                   sha256=sha(st), size_bytes=st.stat().st_size, generated_at=now,
                   previous_contract_source_sha256="1e9752e742a858cf6caecec3df437b8eb16db1ed9344b179ba0600b1856d25b2")
c["rollback_target"] = {"source_contract_version": "1.1.9", "source_contract_path": "outputs/AIV_source_contract_v1_1_9_alignment_20261101/02_gate_source_contract_v1_1_9.json",
    "source_contract_sha256": OLDSHA["contract"], "pre_switch_gate_pointer_sha256": OLDSHA["pointer"], "pre_switch_config_sha256": OLDSHA["config"],
    "note": "Restore resource_coverage_preflight_formal_current.json to the pre-switch bytes (sha above) to roll back."}
c["resource_preflight_preservation"] = {"gate_version": "1.1.9", "gate_status_rebuild": True,
    "rebuild_scope": "rows listed in expected_diff.csv only; all other rows byte-identical",
    "runtime_old_sha256": c["resource_preflight_preservation"]["runtime_old_sha256"],
    "evaluation_methods": "Inherited unchanged from ResourceCoveragePreflightV118"}
ct = put("contract", json.dumps(c, ensure_ascii=False, indent=2) + "\n")
# 5 config
cfg = json.loads(OLD["config"].read_text(encoding="utf-8-sig"))
cfg.update(gate_version="1.1.9", source_contract_version="1.1.10", source_contract_path=REL["contract"], source_contract_sha256=sha(ct),
           runtime_script=REL["runtime"], runtime_script_sha256=sha(rt), guarded_report_launcher=REL["launcher"], guarded_report_launcher_sha256=sha(lc),
           rollback_gate_version="1.1.8", rollback_source_contract_version="1.1.9",
           rollback_config_path=f"{G}/config/resource_coverage_preflight_gate_v1_1_8_source_contract_v1_1_9.json",
           rollback_config_sha256=OLDSHA["config"], rollback_state="PREVIOUS_FORMAL_CURRENT")
cf = put("config", json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
# 6 pointer (stage: formal_current へ置換するのは社長確認②のあと)
p = json.loads(OLD["pointer"].read_text(encoding="utf-8-sig"))
p.update(gate_version="1.1.9", source_contract_version="1.1.10", source_contract_path=REL["contract"], source_contract_sha256=sha(ct),
         config_path=REL["config"], config_sha256=sha(cf), runtime_script=REL["runtime"], runtime_script_sha256=sha(rt),
         guarded_report_launcher=REL["launcher"], guarded_report_launcher_sha256=sha(lc), rollback_gate_version="1.1.8")
pf = put("pointer", json.dumps(p, ensure_ascii=False, indent=2) + "\n")
man = {k: {"path": REL[k], "sha256": sha(OUT / "formal_root_overlay" / REL[k])} for k in REL}
man["_old_sha256"] = OLDSHA
(OUT / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({k: v["sha256"][:12] for k, v in man.items() if k != "_old_sha256"}, indent=1))
