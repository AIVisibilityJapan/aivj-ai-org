#!/usr/bin/env python3
"""汎用リリースstage作成（Gate判定表・Common Asset・selector・binding を一括で次版へ。正式ファイルは書かない）。
和泉市専用だった aiv_release_stage_selector.py の汎用版。版名は現行ポインタから読み、パッチ番号を +1 する（直書きなし）。
使い方:
  py scripts\\aiv_release_build.py --formal-root "<...\\AI Visibility>" --out <新規フォルダ>
        [--append-stage <aiv_resource_append_v2 の stage>] [--gate-stage <aiv_gate_release_stage の stage>] [--date 20261114]
  （--append-stage と --gate-stage の少なくとも一方が必要）
出力: <out>/formal_root_overlay/... と manifest.json（format 2: place=新規配置, replace=差替え）。検証・切替は aiv_release_switch_v2.py。
どの置換も、見つからなければ停止（fail closed）。
"""
import argparse, csv, datetime, hashlib, json, re, sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument('--formal-root', required=True); ap.add_argument('--out', required=True)
ap.add_argument('--append-stage'); ap.add_argument('--gate-stage'); ap.add_argument('--date')
A = ap.parse_args()
if not (A.append_stage or A.gate_stage):
    sys.exit('STOP: --append-stage か --gate-stage が必要')
FR = Path(A.formal_root); OUT = Path(A.out)
if OUT.exists(): sys.exit(f'STOP: out が既に存在: {OUT}')
OUT.mkdir(parents=True); ov = OUT / 'formal_root_overlay'
JST = datetime.timezone(datetime.timedelta(hours=9))
now = datetime.datetime.now(JST).isoformat(); DATE = A.date or datetime.datetime.now(JST).strftime('%Y%m%d')
G = '03_実行基盤・コード/03_診断レポート/現行レポート基盤/03_generated'

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def jl(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def js(o): return json.dumps(o, ensure_ascii=False, indent=2) + '\n'
def rdc(p):
    with open(p, encoding='utf-8-sig', newline='') as f: return list(csv.DictReader(f))
def put(rel, data):
    p = ov / rel; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode('utf-8')); return p
def bump(v): a, b, c = v.split('.'); return f'{a}.{b}.{int(c) + 1}'
def us(v): return v.replace('.', '_')
def nd(v): return v.replace('.', '')
def rsub(s, pat, rep, n=None, flags=0):
    r, c = re.subn(pat, rep, s, flags=flags); assert c >= 1 and (n is None or c == n), (pat[:70], c); return r
def metrics(rows):
    by = {}
    for r in rows: by.setdefault(r['municipality_id'], []).append(r)
    cnt = {m: sum(1 for x in v if x['common_asset_id']) for m, v in by.items()}
    return dict(targets=len(by), slots=len(rows), top3=sum(1 for c in cnt.values() if c == 3), top1=sum(1 for c in cnt.values() if c == 1),
                top0=sum(1 for c in cnt.values() if c == 0), top2=sum(1 for c in cnt.values() if c == 2))

CFG = FR / G / 'config'
sp_old = jl(CFG / 'diagnostic_resource_selector_formal_current.json')
gp_old = jl(CFG / 'resource_coverage_preflight_formal_current.json')
b_old = jl(CFG / 'diagnostic_light_report_selector_binding.json')
pin_old = jl(FR / sp_old['pin_path']); sc_old = jl(FR / pin_old['selector_config_path']); cp_old = jl(FR / sp_old['common_asset_pin_path'])
contract_path_old = gp_old['source_contract_path']; c_old = jl(FR / contract_path_old); cfg_old = jl(FR / gp_old['config_path'])
P = dict(sel=sp_old['formal_selector_version'], ca=sp_old['common_asset_version'], al=sp_old['common_alias_version'],
         gate=gp_old['gate_version'], con=gp_old['source_contract_version'], bind=b_old['binding_version'])
V = {k: bump(v) for k, v in P.items()}
assert sha(CFG / 'diagnostic_resource_selector_formal_current.json') == pin_old['current_pointer_sha256'], 'selector pointer と pin が不一致'
assert sha(CFG / 'resource_coverage_preflight_formal_current.json') == b_old['resource_preflight_pointer_sha256'], 'Gate pointer と binding が不一致'
pre_ptr = dict(sel_ptr=sha(CFG / 'diagnostic_resource_selector_formal_current.json'), binding=sha(CFG / 'diagnostic_light_report_selector_binding.json'),
               gate_ptr=sha(CFG / 'resource_coverage_preflight_formal_current.json'))
print('現行版', P, '→ 新版', V)

# ---- 1 data files ----
D = f'outputs/AIV_common_asset_v{us(V["ca"])}_selector_v{us(V["sel"])}_{DATE}'
old_slots_rel = sc_old['formal_slot_path']
slot_name = rsub(rsub(Path(old_slots_rel).name, r'selector_v\d+(?:_\d+)*', 'selector_v' + us(V['sel']), 1), r'common_v\d+(?:_\d+)*', 'common_v' + us(V['ca']), 1)
R = dict(alias=f'{D}/02_ALIAS/common_tourism_asset_alias_v{us(V["al"])}.csv',
         relation=f'{D}/03_RELATIONS/common_asset_municipality_relation_v{us(V["ca"])}.csv',
         slots=f'{D}/01_SELECTOR/{slot_name}')
old_paths = dict(alias=cp_old['alias_path'], relation=cp_old['relation_path'], slots=old_slots_rel)
src = {}; master_new = False; changed_slots = set(); gate_changed = {}
if A.append_stage:
    APS = Path(A.append_stage); vs = jl(APS / 'validation.json'); assert vs['status'] == 'PASS', 'append stage が PASS でない'
    for f in APS.glob('*_stage.csv'):
        if f.name.startswith('common_asset_municipality_relation'): src['relation'] = f
        elif f.name.startswith('common_tourism_asset_alias'): src['alias'] = f
        elif f.name.startswith('diagnostic_selector'): src['slots'] = f
        elif f.name.startswith('common_tourism_asset_master'): src['master'] = f
    assert {'relation', 'alias', 'slots'} <= set(src), src
    assert vs['checks']['baseline_unchanged'] and not vs['checks']['changed_outside_spec']
    master_new = 'master' in src; changed_slots = set(vs['checks']['changed_municipalities'])
for k in ('alias', 'relation', 'slots'):
    put(R[k], (src[k].read_bytes() if k in src else (FR / old_paths[k]).read_bytes()))
if master_new:
    R['master'] = f'{D}/01_ASSET_MASTER/common_tourism_asset_master_v{us(V["ca"])}.csv'; put(R['master'], src['master'].read_bytes())
new_slots = rdc(ov / R['slots']); old_slots = rdc(FR / old_slots_rel)
mo, mn = metrics(old_slots), metrics(new_slots)
assert mo == sc_old['expected_metrics'], ('旧スロット指標が現行configと不一致', mo, sc_old['expected_metrics'])
assert len(old_slots) == len(new_slots)
ch = {a['municipality_id'] for a, b in zip(old_slots, new_slots) if a != b}
assert ch == changed_slots, ('スロットの変更自治体が追記stageの申告と不一致', ch, changed_slots)

# ---- 2 Gate status (optional) ----
status_new = None
if A.gate_stage:
    GS = Path(A.gate_stage); gv = jl(GS / 'validation.json')
    assert gv.get('formal_gate_modified') is False and gv.get('unexpected_changes') == 0
    GSR = f'outputs/AIV_resource_preflight_gate_v{us(V["gate"])}_ledger_review_{DATE}/sources/gate_municipality_status_v{us(V["gate"])}.csv'
    status_new = put(GSR, (GS / 'gate_municipality_status_stage.csv').read_bytes())
    gate_changed = {d['municipality_id']: d for d in rdc(GS / 'expected_diff.csv') if d['column'] == 'preflight_result'}
    old_status_src = next(s for s in c_old['sources'] if s['logical_source_name'] == 'gate_municipality_status')
    base_rows = {r['municipality_id']: r for r in rdc(FR / old_status_src['path_relative_to_formal_root'])}
    new_rows = rdc(status_new)
    assert len(new_rows) == len(base_rows) and {r['municipality_id'] for r in new_rows} == set(base_rows)
    chg = {r['municipality_id'] for r in new_rows if r != base_rows[r['municipality_id']]}
    assert chg == set(gate_changed) == set(gv['changed_municipalities']), ('Gate表の変更行が不一致', chg)

# ---- 3 common asset pin ----
cp = dict(cp_old)
CPN = rsub(Path(sp_old['common_asset_pin_path']).name, r'common_asset_v[\d_]+_apa', f'common_asset_v{us(V["ca"])}_apa', 1)
cp.update(pin_id=rsub(cp_old['pin_id'], r'COMMON_ASSET_V[\d_]+_APA', f'COMMON_ASSET_V{us(V["ca"])}_APA', 1), common_asset_version=V['ca'], common_alias_version=V['al'],
          alias_path=R['alias'], alias_sha256=sha(ov / R['alias']), relation_path=R['relation'], relation_sha256=sha(ov / R['relation']))
if master_new: cp.update(asset_master_path=R['master'], asset_master_sha256=sha(ov / R['master']))
cp['rollback_target'] = {'common_asset': P['ca'], 'common_alias': P['al'], 'appearance_mapping': cp_old['appearance_mapping_version'], 'apa_mapping': cp_old['apa_mapping_version'],
                         'selector': P['sel'], 'gate': P['gate'], 'source_contract': P['con'], 'binding': P['bind']}
cpf = put(f'{G}/config/{CPN}', js(cp))

# ---- 4 selector config / launcher / pointer / pin ----
sc = dict(sc_old); sc.update(selector_version=V['sel'], formal_slot_path=R['slots'], formal_slot_sha256=sha(ov / R['slots']), common_asset_version=V['ca'],
                             common_asset_pin_path=f'{G}/config/{CPN}', expected_metrics=mn, rollback_target=cp['rollback_target'])
SCN = f'diagnostic_resource_selector_v{us(V["sel"])}.json'; scf = put(f'{G}/config/{SCN}', js(sc))
ls = (FR / sp_old['formal_launcher']).read_text(encoding='utf-8')
ls = ls.replace(us(P['sel']), us(V['sel']))
ls = ls.replace('V' + nd(P['sel']), 'V' + nd(V['sel']))
assert us(P['sel']) not in ls and nd(P['sel']) not in ls
LSN = f'{G}/scripts/aiv_selector_v{us(V["sel"])}_pinned.py'; lsf = put(LSN, ls)
PINN = f'diagnostic_resource_selector_v{us(V["sel"])}_pin.json'
sp = dict(sp_old); sp.update(formal_selector_version=V['sel'], formal_launcher=LSN, pin_path=f'{G}/config/{PINN}', selector_config_sha256=sha(scf), common_asset_version=V['ca'],
                             common_alias_version=V['al'], common_asset_pin_path=f'{G}/config/{CPN}', rollback_target=cp['rollback_target'])
spf = put(f'{G}/config/diagnostic_resource_selector_formal_current.json', js(sp))
pin = dict(pin_old); pin.update(pin_id=rsub(pin_old['pin_id'], r'SELECTOR_V[\d_]+_FORMAL', f'SELECTOR_V{us(V["sel"])}_FORMAL', 1), selector_version=V['sel'], current_pointer_sha256=sha(spf),
                                selector_config_path=f'{G}/config/{SCN}', selector_config_sha256=sha(scf), launcher_path=LSN, launcher_sha256=sha(lsf),
                                common_asset_pin_path=f'{G}/config/{CPN}', common_asset_pin_sha256=sha(cpf))
pinf = put(f'{G}/config/{PINN}', js(pin))

# ---- 5 Gate adapter / launcher / contract / config / pointer ----
rt_old = FR / gp_old['runtime_script']; ad = rt_old.read_text(encoding='utf-8')
oldc = sha(FR / contract_path_old)
ad = rsub(ad, r"'common_asset':'[\d.]+','common_alias':'[\d.]+'", f"'common_asset':'{V['ca']}','common_alias':'{V['al']}'", 1)
ad = rsub(ad, r"('apa_mapping':'[\d.]+',)'selector':'[\d.]+'", rf"\1'selector':'{V['sel']}'", 1)
ad = rsub(ad, r"'resource_preflight':'[\d.]+'", f"'resource_preflight':'{V['gate']}'", 1)
ad = rsub(ad, r"contract\.get\('source_contract_version'\)=='[\d.]+'", f"contract.get('source_contract_version')=='{V['con']}'", 1)
ad = rsub(ad, r"contract\.get\('gate_version'\)=='[\d.]+'", f"contract.get('gate_version')=='{V['gate']}'", 1)
ad = rsub(ad, r"contract\['previous_version'\]=='[\d.]+' and contract\['previous_contract_sha256'\]=='[0-9a-f]{64}'",
          f"contract['previous_version']=='{P['con']}' and contract['previous_contract_sha256']=='{oldc}'", 1)
ad = rsub(ad, r"self\.pointer\.get\('gate_version'\)=='[\d.]+'", f"self.pointer.get('gate_version')=='{V['gate']}'", 1)
ad = rsub(ad, r"self\.pointer\.get\('source_contract_version'\)=='[\d.]+'", f"self.pointer.get('source_contract_version')=='{V['con']}'", 1)
ad = rsub(ad, r"common_asset_v[\d_]+_apa_mapping_v[\d_]+_formal_pin\.json", CPN)
ad = rsub(ad, r"diagnostic_resource_selector_v[\d_]+_pin\.json", PINN)
ad = rsub(ad, r"pin\.get\('selector_version'\)=='[\d.]+'", f"pin.get('selector_version')=='{V['sel']}'", 1)
ad = rsub(ad, 'SourceContractV' + nd(P['con']), 'SourceContractV' + nd(V['con']))
assert 'SourceContractV' + nd(P['con']) not in ad
adn = f'{G}/scripts/aiv_resource_coverage_preflight_source_contract_v{us(V["con"])}.py'; adf = put(adn, ad)
gl = (FR / gp_old['guarded_report_launcher']).read_text(encoding='utf-8')
gl = rsub(gl, r'aiv_resource_coverage_preflight_source_contract_v\d+(?:_\d+)*', f'aiv_resource_coverage_preflight_source_contract_v{us(V["con"])}')
gl = rsub(gl, 'SourceContractV' + nd(P['con']), 'SourceContractV' + nd(V['con']))
gl = rsub(gl, r"'gate_version':'[\d.]+',\s*'source_contract_version':'[\d.]+'", f"'gate_version':'{V['gate']}',\n        'source_contract_version':'{V['con']}'", 1)
gln = f'{G}/scripts/aiv_generate_light_report_source_contract_guarded_v{us(V["con"])}.py'; glf = put(gln, gl)

c = json.loads(json.dumps(c_old))
c.update(source_contract_version=V['con'], gate_version=V['gate'], generated_at=now, created_at=now, previous_version=P['con'],
         previous_contract_path=contract_path_old, previous_contract_sha256=oldc)
c['creation_reason'] = (f'Append-only: selector {V["sel"]} / common asset {V["ca"]} rebuilt per append stage' + (f' (new asset master rows)' if master_new else '') +
                        (f'; Gate status rebuilt for ledger-reviewed municipalities {sorted(gate_changed)}' if gate_changed else '; Gate status table unchanged') +
                        '. Evaluation logic unchanged. No measurements or rankings changed.')
c['version_assignment_evidence'] = f'Next unused patch versions after {P["gate"]}/{P["con"]}; derived from the current formal pointers by aiv_release_build.py.'
c['active_resource_versions'].update(common_asset=V['ca'], common_alias=V['al'], selector=V['sel'])
c['bound_versions'].update(common_asset=V['ca'], common_alias=V['al'], selector=V['sel'], resource_preflight=V['gate'])
for s in c['sources']:
    n = s['logical_source_name']
    k = {'common_alias': 'alias', 'common_municipality_relation': 'relation', 'diagnostic_selector_slots': 'slots', 'common_asset_master': 'master'}.get(n)
    if k and (k != 'master' or master_new):
        p = ov / R[k]; rows = rdc(p)
        s.update(path_relative_to_formal_root=R[k], resolved_path_at_build='(stage) ' + R[k], sha256=sha(p), size_bytes=p.stat().st_size, row_count=len(rows), generated_at=now,
                 version={'alias': V['al'], 'relation': V['ca'], 'slots': V['sel'], 'master': V['ca']}[k])
        with open(p, encoding='utf-8-sig', newline='') as f: assert next(csv.reader(f)) == s['schema_columns'], n
    if n == 'diagnostic_selector_current_pointer': s.update(sha256=sha(spf), size_bytes=spf.stat().st_size, version=V['sel'], generated_at=now)
    if n == 'gate_municipality_status' and status_new:
        s.update(previous_contract_source_sha256=s['sha256'], path_relative_to_formal_root=GSR, resolved_path_at_build='(stage) ' + GSR, version=V['gate'],
                 sha256=sha(status_new), size_bytes=status_new.stat().st_size, generated_at=now)
for m in c['bound_manifests']:
    if m['name'].startswith('common_asset_'): m.update(name=CPN, path=f'{G}/config/{CPN}', sha256=sha(cpf))
    if m['name'].startswith('diagnostic_resource_selector_'): m.update(name=PINN, path=f'{G}/config/{PINN}', sha256=sha(pinf))
c['bound_manifest_sha'] = {m['name']: m['sha256'] for m in c['bound_manifests']}
c['rollback_target'] = {'source_contract_version': P['con'], 'source_contract_path': contract_path_old, 'source_contract_sha256': oldc, 'pre_switch_gate_pointer_sha256': pre_ptr['gate_ptr'],
    'pre_switch_config_sha256': sha(FR / gp_old['config_path']), 'pre_switch_selector_pointer_sha256': pre_ptr['sel_ptr'], 'pre_switch_binding_sha256': pre_ptr['binding'],
    'note': 'Restore the replaced files (Gate pointer, selector pointer, binding) to the pre-switch bytes to roll back; see backup_manifest.'}
c['resource_preflight_preservation'].update(gate_version=V['gate'], gate_status_rebuild=bool(status_new),
    rebuild_scope=('rows listed in the gate stage expected_diff only' if status_new else 'none (status table identical to previous Gate)'),
    evaluation_methods='Inherited unchanged from the previous Gate evaluation logic')
cn = f'outputs/AIV_source_contract_v{us(V["con"])}_selector_{us(V["sel"])}_{DATE}/02_gate_source_contract_v{us(V["con"])}.json'; ctf = put(cn, js(c))
cgn = f'{G}/config/resource_coverage_preflight_gate_v{us(V["gate"])}_source_contract_v{us(V["con"])}.json'
cfg = dict(cfg_old); cfg.update(gate_version=V['gate'], source_contract_version=V['con'], source_contract_path=cn, source_contract_sha256=sha(ctf), runtime_script=adn, runtime_script_sha256=sha(adf),
    guarded_report_launcher=gln, guarded_report_launcher_sha256=sha(glf), rollback_gate_version=P['gate'], rollback_source_contract_version=P['con'],
    rollback_config_path=gp_old['config_path'], rollback_config_sha256=sha(FR / gp_old['config_path']), rollback_state='PREVIOUS_FORMAL_CURRENT')
cgf = put(cgn, js(cfg))
gp = dict(gp_old); gp.update(gate_version=V['gate'], source_contract_version=V['con'], source_contract_path=cn, source_contract_sha256=sha(ctf), config_path=cgn, config_sha256=sha(cgf),
    runtime_script=adn, runtime_script_sha256=sha(adf), guarded_report_launcher=gln, guarded_report_launcher_sha256=sha(glf), rollback_gate_version=P['gate'])
gpf = put(f'{G}/config/resource_coverage_preflight_formal_current.json', js(gp))

# ---- 6 binding ----
b = dict(b_old)
fac = rsub(b_old['selector_factory'], r'v[\d_]+$', 'v' + us(V['sel']), 1)
b.update(binding_version=V['bind'], formal_selector_version=V['sel'], formal_common_asset_version=V['ca'], formal_common_alias_version=V['al'], current_pointer_sha256=sha(spf),
    formal_launcher_path=LSN, formal_selector_pin_path=f'{G}/config/{PINN}', formal_selector_pin_sha256=sha(pinf), selector_factory=fac,
    formal_resource_preflight_version=V['gate'], formal_source_contract_version=V['con'], resource_preflight_pointer_sha256=sha(gpf))
bf = put(f'{G}/config/diagnostic_light_report_selector_binding.json', js(b))
BVN = f'{G}/config/diagnostic_light_report_selector_binding_v{us(V["bind"])}.json'; put(BVN, bf.read_bytes())

place = [R[k] for k in ('alias', 'relation', 'slots') ] + ([R['master']] if master_new else []) + ([GSR] if status_new else []) + \
        [f'{G}/config/{CPN}', f'{G}/config/{SCN}', LSN, f'{G}/config/{PINN}', adn, gln, cn, cgn, BVN]
replace = [dict(path=f'{G}/config/diagnostic_resource_selector_formal_current.json', old_sha256=pre_ptr['sel_ptr']),
           dict(path=f'{G}/config/diagnostic_light_report_selector_binding.json', old_sha256=pre_ptr['binding']),
           dict(path=f'{G}/config/resource_coverage_preflight_formal_current.json', old_sha256=pre_ptr['gate_ptr'])]   # Gate pointer は最後
filled = {}
for r in new_slots: filled[r['municipality_id']] = filled.get(r['municipality_id'], 0) + (1 if r['common_asset_id'] else 0)
checks = [{'municipality_id': m, 'selected': filled.get(m, 0), 'gate': (['RESOURCE_PREFLIGHT_PASS', 'TRUE'] if m in gate_changed else None)} for m in sorted(set(changed_slots) | set(gate_changed))]
man = {'format': 3, 'place': [{'path': p, 'sha256': sha(ov / p)} for p in place], 'replace': [{**r, 'sha256': sha(ov / r['path'])} for r in replace],
       'versions': V, 'previous_versions': P, 'expected_metrics_new': mn, 'expected_metrics_old': mo,
       'changed_municipalities_slots': sorted(changed_slots), 'changed_municipalities_gate': sorted(gate_changed), 'post_check': {'checks': checks}}
(OUT / 'manifest.json').write_text(js(man), encoding='utf-8')
print(json.dumps({'metrics_old': mo, 'metrics_new': mn, 'slots_changed': sorted(changed_slots), 'gate_changed': sorted(gate_changed), 'master_new': master_new, 'post_check': checks}, ensure_ascii=False, indent=1))
for k in ('place', 'replace'):
    for e in man[k]: print(k, e['sha256'][:12], e['path'][-70:])
