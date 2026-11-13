#!/usr/bin/env python3
"""selector追記版 + Gate新版 + binding の一括 stage 作成（正式ファイルは書かない）。
使い方:
  python aiv_release_stage_selector.py --out <新規フォルダ> --append-stage <追記stage(v2)> --prev-gate-stage <Gate新版stage_20261114>
         --config-dir <現行config一式> --selector-launcher <aiv_selector_v1_5_51_pinned.py> --baseline-root <現行の正式ルート>
入力は読むだけ。出力: <out>/formal_root_overlay/... と manifest.json（place=新規配置, replace=差替え）
"""
import argparse, csv, datetime, hashlib, json, re
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument('--out', required=True); ap.add_argument('--append-stage', required=True)
ap.add_argument('--prev-gate-stage', required=True); ap.add_argument('--config-dir', required=True)
ap.add_argument('--selector-launcher', required=True)
ap.add_argument('--baseline-root', required=True, help='現行の正式ルート（スロットCSVの旧版を読む）')
A = ap.parse_args()
OUT = Path(A.out); OUT.mkdir(parents=True)
ov = OUT / 'formal_root_overlay'
G = '03_実行基盤・コード/03_診断レポート/現行レポート基盤/03_generated'
V = dict(sel='1.5.52', ca='1.1.32', al='1.1.25', gate='1.1.10', con='1.1.11', bind='1.0.31')
PREV = dict(sel='1.5.51', ca='1.1.31', al='1.1.24', gate='1.1.9', con='1.1.10', bind='1.0.30')
CFG = Path(A.config_dir); APS = Path(A.append_stage); PG = Path(A.prev_gate_stage) / 'formal_root_overlay'
BASE = Path(A.baseline_root)
now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat()

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def jl(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def put(rel, data):
    p = ov / rel; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode('utf-8')); return p
def js(o): return json.dumps(o, ensure_ascii=False, indent=2) + '\n'
def sub(s, a, b, n=None):
    c = s.count(a); assert c >= 1 and (n is None or c == n), (a[:60], c); return s.replace(a, b)
pre_ptr_sha = {k: sha(CFG / f) for k, f in [('sel_ptr', 'diagnostic_resource_selector_formal_current.json'), ('binding', 'diagnostic_light_report_selector_binding.json')]}
pm = jl(PG.parent / 'manifest.json')   # Gate 1.1.9 stage manifest
assert sha(PG / pm['pointer']['path']) == pm['pointer']['sha256']
gate_ptr_before = pm['pointer']['sha256']
M, ASSETS = {}, {}   # new files (place) / replaced files

# ---- 1 data files (alias / relation / slots) ----
D = 'outputs/AIV_common_asset_v1_1_32_selector_v1_5_52_20261114'
R = dict(
    alias=f'{D}/02_ALIAS/common_tourism_asset_alias_v1_1_25.csv',
    relation=f'{D}/03_RELATIONS/common_asset_municipality_relation_v1_1_32.csv',
    slots=f'{D}/01_SELECTOR/diagnostic_selector_v1_5_52_formal_slots_common_v1_1_32_apa_mapping_v1_1_30.csv')
src = dict(alias='common_tourism_asset_alias_1_5_52_stage.csv', relation='common_asset_municipality_relation_1_5_52_stage.csv', slots='diagnostic_selector_v1_5_52_formal_slots_stage.csv')
for k in R: put(R[k], (APS / src[k]).read_bytes())
vstage = jl(APS / 'validation.json'); assert vstage['status'] == 'PASS' and vstage['checks']['changed_municipalities'] == ['MUNI_272191']
# slot sanity + expected metrics
def read_csv(p):
    with open(p, encoding='utf-8-sig', newline='') as f: return list(csv.DictReader(f))
new_slots = read_csv(ov / R['slots'])
def metrics(rows):
    by = {}
    for r in rows: by.setdefault(r['municipality_id'], []).append(r)
    cnt = {m: sum(1 for x in v if x['common_asset_id']) for m, v in by.items()}
    return dict(targets=len(by), slots=len(rows), top3=sum(1 for c in cnt.values() if c == 3), top1=sum(1 for c in cnt.values() if c == 1),
                top0=sum(1 for c in cnt.values() if c == 0), top2=sum(1 for c in cnt.values() if c == 2))
old_slots_path = BASE / 'outputs/AIV_diagnostic_selector_v1_5_51_reaudit9_20261030/01_SELECTOR/diagnostic_selector_v1_5_51_formal_slots_common_v1_1_31_apa_mapping_v1_1_30.csv'
sel_old = jl(CFG / 'diagnostic_resource_selector_v1_5_51.json')
if old_slots_path.is_file():
    old_slots = read_csv(old_slots_path)
    mo, mn = metrics(old_slots), metrics(new_slots)
    assert mo == sel_old['expected_metrics'], (mo, sel_old['expected_metrics'])   # 旧版の指標が config と一致すること
    ch = [(a['municipality_id']) for a, b in zip(old_slots, new_slots) if a != b]
    assert set(ch) == {'MUNI_272191'} and len(old_slots) == len(new_slots), set(ch)
else:   # 旧スロットCSVが読めない環境（試験用）: config の旧指標からの差が和泉市(0→2)だけと一致するかで代替
    print('WARN: baseline slots not found; using expected_metrics from selector config 1.5.51 (full row diff skipped)')
    mo, mn = dict(sel_old['expected_metrics']), metrics(new_slots)
    exp = dict(mo); exp['top0'] -= 1; exp['top2'] += 1
    assert mn == exp, (mn, exp)
    ch = ['MUNI_272191']

# ---- 2 common asset pin 1.1.32 ----
cp_old = jl(CFG / 'common_asset_v1_1_31_apa_mapping_v1_1_30_formal_pin.json')
cp = dict(cp_old); cp.update(pin_id='AIV_COMMON_ASSET_V1_1_32_APA_MAPPING_V1_1_30_FORMAL_PIN', common_asset_version=V['ca'], common_alias_version=V['al'],
    alias_path=R['alias'], alias_sha256=sha(ov / R['alias']), relation_path=R['relation'], relation_sha256=sha(ov / R['relation']))
cp['rollback_target'] = {'common_asset': PREV['ca'], 'common_alias': PREV['al'], 'appearance_mapping': '1.1.12', 'apa_mapping': '1.1.30',
                         'selector': PREV['sel'], 'gate': PREV['gate'], 'source_contract': PREV['con'], 'binding': PREV['bind']}
CPN = 'common_asset_v1_1_32_apa_mapping_v1_1_30_formal_pin.json'
cpf = put(f'{G}/config/{CPN}', js(cp))

# ---- 3 selector config 1.5.52 / launcher / pointer / pin ----
sc = dict(sel_old); sc.update(selector_version=V['sel'], formal_slot_path=R['slots'], formal_slot_sha256=sha(ov / R['slots']),
    common_asset_version=V['ca'], common_asset_pin_path=f'{G}/config/{CPN}', expected_metrics=mn, rollback_target=cp['rollback_target'])
scf = put(f'{G}/config/diagnostic_resource_selector_v1_5_52.json', js(sc))
ls = Path(A.selector_launcher).read_text(encoding='utf-8')
ls = sub(ls, '1_5_51', '1_5_52'); ls = sub(ls, 'V1551', 'V1552')
lsf = put(f'{G}/scripts/aiv_selector_v1_5_52_pinned.py', ls)
sp = jl(CFG / 'diagnostic_resource_selector_formal_current.json')
sp.update(formal_selector_version=V['sel'], formal_launcher=f'{G}/scripts/aiv_selector_v1_5_52_pinned.py', pin_path=f'{G}/config/diagnostic_resource_selector_v1_5_52_pin.json',
    selector_config_sha256=sha(scf), common_asset_version=V['ca'], common_alias_version=V['al'], common_asset_pin_path=f'{G}/config/{CPN}',
    rollback_target=cp['rollback_target'])
spf = put(f'{G}/config/diagnostic_resource_selector_formal_current.json', js(sp))   # replace
pin = jl(CFG / 'diagnostic_resource_selector_v1_5_51_pin.json')
pin.update(pin_id='AIV_DIAGNOSTIC_RESOURCE_SELECTOR_V1_5_52_FORMAL_PIN', selector_version=V['sel'], current_pointer_sha256=sha(spf),
    selector_config_path=f'{G}/config/diagnostic_resource_selector_v1_5_52.json', selector_config_sha256=sha(scf),
    launcher_path=f'{G}/scripts/aiv_selector_v1_5_52_pinned.py', launcher_sha256=sha(lsf),
    common_asset_pin_path=f'{G}/config/{CPN}', common_asset_pin_sha256=sha(cpf))
PINN = 'diagnostic_resource_selector_v1_5_52_pin.json'
pinf = put(f'{G}/config/{PINN}', js(pin))

# ---- 4 Gate adapter 1.1.11 / launcher / contract / config / pointer ----
ad = (PG / pm['runtime']['path']).read_text(encoding='utf-8')
oldc = sha(PG / pm['contract']['path'])
ad = sub(ad, "'common_asset':'1.1.31','common_alias':'1.1.24','appearance_mapping':'1.1.12','apa_mapping':'1.1.30','selector':'1.5.51'",
             "'common_asset':'1.1.32','common_alias':'1.1.25','appearance_mapping':'1.1.12','apa_mapping':'1.1.30','selector':'1.5.52'", 1)
ad = sub(ad, "'resource_preflight':'1.1.9'", "'resource_preflight':'1.1.10'", 1)
ad = sub(ad, "contract.get('source_contract_version')=='1.1.10'", "contract.get('source_contract_version')=='1.1.11'", 1)
ad = sub(ad, "contract.get('gate_version')=='1.1.9'", "contract.get('gate_version')=='1.1.10'", 1)
ad = sub(ad, "contract['previous_version']=='1.1.9' and contract['previous_contract_sha256']=='ff4551b96d14b0a90743e646080a04e13f9f63b04c7d3ec847f84fc41ab0e18b'",
             f"contract['previous_version']=='1.1.10' and contract['previous_contract_sha256']=='{oldc}'", 1)
ad = sub(ad, "self.pointer.get('gate_version')=='1.1.9'", "self.pointer.get('gate_version')=='1.1.10'", 1)
ad = sub(ad, "self.pointer.get('source_contract_version')=='1.1.10'", "self.pointer.get('source_contract_version')=='1.1.11'", 1)
ad = sub(ad, 'common_asset_v1_1_31_apa_mapping_v1_1_30_formal_pin.json', CPN)
ad = sub(ad, 'diagnostic_resource_selector_v1_5_51_pin.json', PINN)
ad = sub(ad, "pin.get('selector_version')=='1.5.51'", "pin.get('selector_version')=='1.5.52'", 1)
ad = sub(ad, 'SourceContractV1110', 'SourceContractV1111'); ad = sub(ad, 'source_contract_v1_1_10', 'source_contract_v1_1_11') if 'source_contract_v1_1_10' in ad else ad
ad = sub(ad, 'adapter 1.1.10 (Gate 1.1.9:', 'adapter 1.1.11 (Gate 1.1.10: selector 1.5.52 / common asset 1.1.32 rebound;') if 'adapter 1.1.10 (Gate 1.1.9:' in ad else ad
assert 'V1110' not in ad
adn = f'{G}/scripts/aiv_resource_coverage_preflight_source_contract_v1_1_11.py'
adf = put(adn, ad)
gl = (PG / pm['launcher']['path']).read_text(encoding='utf-8')
gl = sub(gl, 'aiv_resource_coverage_preflight_source_contract_v1_1_10', 'aiv_resource_coverage_preflight_source_contract_v1_1_11')
gl = sub(gl, 'SourceContractV1110', 'SourceContractV1111')
gl = sub(gl, "'gate_version':'1.1.9',\n        'source_contract_version':'1.1.10'", "'gate_version':'1.1.10',\n        'source_contract_version':'1.1.11'", 1)
assert 'V1110' not in gl
gln = f'{G}/scripts/aiv_generate_light_report_source_contract_guarded_v1_1_11.py'
glf = put(gln, gl)
c = jl(PG / pm['contract']['path'])
c.update(source_contract_version=V['con'], gate_version=V['gate'], generated_at=now, created_at=now,
    previous_version=PREV['con'], previous_contract_path=pm['contract']['path'], previous_contract_sha256=oldc)
c['creation_reason'] = ('Append-only: diagnostic selector 1.5.52 (Izumi city resources appended; alias/relation/slots rebuilt per append stage) rebound into Gate; '
                        'Gate status table unchanged from 1.1.9; evaluation logic unchanged (inherited from 1.1.8). No measurements or rankings changed.')
c['version_assignment_evidence'] = 'Next unused patch versions after 1.1.9/1.1.10; names confirmed by the president on 2026-11-14.'
c['active_resource_versions'].update(common_asset=V['ca'], common_alias=V['al'], selector=V['sel'])
c['bound_versions'].update(common_asset=V['ca'], common_alias=V['al'], selector=V['sel'], resource_preflight=V['gate'])
chg = {}
for s in c['sources']:
    n = s['logical_source_name']
    if n in ('common_alias', 'common_municipality_relation', 'diagnostic_selector_slots'):
        k = dict(common_alias='alias', common_municipality_relation='relation', diagnostic_selector_slots='slots')[n]
        p = ov / R[k]; rows = read_csv(p)
        s.update(path_relative_to_formal_root=R[k], resolved_path_at_build='(stage) ' + R[k], sha256=sha(p), size_bytes=p.stat().st_size, row_count=len(rows), generated_at=now,
                 version=dict(common_alias=V['al'], common_municipality_relation=V['ca'], diagnostic_selector_slots=V['sel'])[n])
        with open(p, encoding='utf-8-sig', newline='') as f: assert next(csv.reader(f)) == s['schema_columns'], n
    if n == 'diagnostic_selector_current_pointer':
        s.update(sha256=sha(spf), size_bytes=spf.stat().st_size, version=V['sel'], generated_at=now)
mf = []
for m in c['bound_manifests']:
    if m['name'].startswith('common_asset_'): m.update(name=CPN, path=f'{G}/config/{CPN}', sha256=sha(cpf))
    if m['name'].startswith('diagnostic_resource_selector_'): m.update(name=PINN, path=f'{G}/config/{PINN}', sha256=sha(pinf))
c['bound_manifest_sha'] = {m['name']: m['sha256'] for m in c['bound_manifests']}
cn = f"outputs/AIV_source_contract_v1_1_11_selector_1_5_52_20261114/02_gate_source_contract_v1_1_11.json"
# rollback (filled after pointer/config known; pointer sha before = current Gate pointer)
c['rollback_target'] = {'source_contract_version': PREV['con'], 'source_contract_path': pm['contract']['path'], 'source_contract_sha256': oldc,
    'pre_switch_gate_pointer_sha256': gate_ptr_before, 'pre_switch_config_sha256': pm['config']['sha256'],
    'pre_switch_selector_pointer_sha256': pre_ptr_sha['sel_ptr'], 'pre_switch_binding_sha256': pre_ptr_sha['binding'],
    'note': 'Restore the replaced files (Gate pointer, selector pointer, binding) to the pre-switch bytes to roll back; see backup_manifest.'}
c['resource_preflight_preservation'].update(gate_version=V['gate'], gate_status_rebuild=False,
    rebuild_scope='none (status table identical to Gate 1.1.9)', evaluation_methods='Inherited unchanged from ResourceCoveragePreflightV118')
left = [l for l in js(c).splitlines() if re.search(r'1\.5\.51|1\.1\.31|v1_5_51|v1_1_31', l) and 'AIV_common_asset_v1_1_31' not in l and 'asset_master' not in l and 'v1_1_31.csv' not in l and 'Master' not in l]
ctf = put(cn, js(c))
cgn = f'{G}/config/resource_coverage_preflight_gate_v1_1_10_source_contract_v1_1_11.json'
cfg = jl(PG / pm['config']['path'])
cfg.update(gate_version=V['gate'], source_contract_version=V['con'], source_contract_path=cn, source_contract_sha256=sha(ctf), runtime_script=adn, runtime_script_sha256=sha(adf),
    guarded_report_launcher=gln, guarded_report_launcher_sha256=sha(glf), rollback_gate_version=PREV['gate'], rollback_source_contract_version=PREV['con'],
    rollback_config_path=pm['config']['path'], rollback_config_sha256=pm['config']['sha256'], rollback_state='PREVIOUS_FORMAL_CURRENT')
cgf = put(cgn, js(cfg))
gp = jl(PG / pm['pointer']['path'])
gp.update(gate_version=V['gate'], source_contract_version=V['con'], source_contract_path=cn, source_contract_sha256=sha(ctf), config_path=cgn, config_sha256=sha(cgf),
    runtime_script=adn, runtime_script_sha256=sha(adf), guarded_report_launcher=gln, guarded_report_launcher_sha256=sha(glf), rollback_gate_version=PREV['gate'])
gpf = put(f'{G}/config/resource_coverage_preflight_formal_current.json', js(gp))   # replace

# ---- 5 binding 1.0.31 ----
b = jl(CFG / 'diagnostic_light_report_selector_binding.json')
b.update(binding_version=V['bind'], formal_selector_version=V['sel'], formal_common_asset_version=V['ca'], formal_common_alias_version=V['al'],
    current_pointer_sha256=sha(spf), formal_launcher_path=f'{G}/scripts/aiv_selector_v1_5_52_pinned.py',
    formal_selector_pin_path=f'{G}/config/{PINN}', formal_selector_pin_sha256=sha(pinf), selector_factory='get_pinned_selector_v1_5_52',
    formal_resource_preflight_version=V['gate'], formal_source_contract_version=V['con'], resource_preflight_pointer_sha256=sha(gpf))
bf = put(f'{G}/config/diagnostic_light_report_selector_binding.json', js(b))   # replace
put(f'{G}/config/diagnostic_light_report_selector_binding_v1_0_31.json', bf.read_bytes())

place = [R['alias'], R['relation'], R['slots'], f'{G}/config/{CPN}', f'{G}/config/diagnostic_resource_selector_v1_5_52.json', f'{G}/scripts/aiv_selector_v1_5_52_pinned.py',
         f'{G}/config/{PINN}', adn, gln, cn, cgn, f'{G}/config/diagnostic_light_report_selector_binding_v1_0_31.json']
replace = [dict(path=f'{G}/config/diagnostic_resource_selector_formal_current.json', old_sha256=pre_ptr_sha['sel_ptr']),
           dict(path=f'{G}/config/diagnostic_light_report_selector_binding.json', old_sha256=pre_ptr_sha['binding']),
           dict(path=pm['pointer']['path'], old_sha256=gate_ptr_before)]   # Gate pointer は最後
man = {'format': 2, 'place': [{'path': p, 'sha256': sha(ov / p)} for p in place],
       'replace': [{**r, 'sha256': sha(ov / r['path'])} for r in replace],
       'versions': V, 'previous_versions': PREV, 'expected_metrics_new': mn, 'expected_metrics_old': mo, 'changed_municipalities_slots': sorted(set(ch)),
       'post_check': {'izumi_gate': ['RESOURCE_PREFLIGHT_PASS', 'TRUE'], 'izumi_selected': 2}}
(OUT / 'manifest.json').write_text(js(man), encoding='utf-8')
print(json.dumps({'metrics_old': mo, 'metrics_new': mn, 'leftover_old_version_lines': left[:6]}, ensure_ascii=False, indent=1))
for k in ('place', 'replace'):
    for e in man[k]: print(k, e['sha256'][:12], e['path'][-70:])
