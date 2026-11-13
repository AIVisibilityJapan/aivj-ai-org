#!/usr/bin/env python3
"""Gate+selector+binding 一括リリース（manifest format 2）の検証・切替・戻し。
  検証(正式ルートは読むだけ): python aiv_release_switch.py validate --formal-root R --stage S --work W
  検査のみ                 : python aiv_release_switch.py switch   --formal-root R --stage S
  切替実行                 : ... switch ... --execute --approval-ref REF
  戻し                     : python aiv_release_switch.py rollback --formal-root R --backup B
validate は R をハードリンクで W にクローンし、そこへ適用して新旧を比較する（R は変更されない）。
"""
import argparse, hashlib, json, os, shutil, subprocess, sys, datetime
from pathlib import Path

G = Path('03_実行基盤・コード/03_診断レポート/現行レポート基盤/03_generated')
PROBE = r'''
import sys, json, importlib, runpy, os
sys.dont_write_bytecode = True
root = sys.argv[1]; G = os.path.join(root, '03_実行基盤・コード', '03_診断レポート', '現行レポート基盤', '03_generated')
sys.path.insert(0, os.path.join(G, 'scripts'))
out = {}
def lj(p): return json.load(open(p, encoding='utf-8-sig'))
try:
    gp = lj(os.path.join(G, 'config', 'resource_coverage_preflight_formal_current.json'))
    mod = os.path.splitext(os.path.basename(gp['runtime_script']))[0]
    cls = {'1_1_11': 'ResourceCoveragePreflightSourceContractV1111', '1_1_10': 'ResourceCoveragePreflightSourceContractV1110'}.get(mod[-6:] if mod.endswith('1_1_11') else mod[-6:], 'ResourceCoveragePreflightSourceContractV119')
    cls = 'ResourceCoveragePreflightSourceContractV1111' if mod.endswith('v1_1_11') else 'ResourceCoveragePreflightSourceContractV1110' if mod.endswith('v1_1_10') else 'ResourceCoveragePreflightSourceContractV119'
    a = getattr(importlib.import_module(mod), cls)()
    out['gate'] = {'ok': True, 'version': gp['gate_version'], 'rows': {k: [v.get('preflight_result'), v.get('report_generation_allowed')] for k, v in a.status_by_municipality.items()}}
except Exception as e: out['gate'] = {'ok': False, 'error': repr(e)}
try:
    sp = lj(os.path.join(G, 'config', 'diagnostic_resource_selector_formal_current.json'))
    ns = runpy.run_path(os.path.join(root, sp['formal_launcher']))
    sel = [v for k, v in ns.items() if k.startswith('get_pinned_selector_v')][0]()
    out['selector'] = {'ok': True, 'version': sp['formal_selector_version'], 'sel': {m: json.dumps(sel.select(m), sort_keys=True) for m in sel.reporting_municipality_ids}}
except Exception as e: out['selector'] = {'ok': False, 'error': repr(e)}
try:
    b = importlib.import_module('aiv_light_report_selector_binding')
    ka, md = b.FormalResourceSelectorBinding().select_key_assets('MUNI_272191')
    out['binding'] = {'ok': True, 'izumi': [(k['asset_name'], k['slot_status']) for k in ka], 'binding_version': md['binding_version']}
except Exception as e: out['binding'] = {'ok': False, 'error': repr(e)[:300]}
print(json.dumps(out))   # ASCII のみ出力（-I では PYTHONIOENCODING が効かないため）
'''

def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()

def probe(root):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
    r = subprocess.run([sys.executable, '-I', '-c', PROBE, str(root)], capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)
    try: return json.loads((r.stdout or '').strip().splitlines()[-1])
    except Exception: return {'gate': {'ok': False, 'error': 'PROBE_FAILED'}, 'selector': {'ok': False}, 'binding': {'ok': False}, 'error': ((r.stderr or '') + (r.stdout or ''))[-1500:]}

def load_manifest(S):
    m = json.loads((Path(S) / 'manifest.json').read_text(encoding='utf-8')); assert m.get('format') == 2; return m

def check(F, S, m):
    ov = Path(S) / 'formal_root_overlay'; res = {}
    res['stage_sha_ok'] = all(sha(ov / e['path']) == e['sha256'] for e in m['place'] + m['replace'])
    conf = [e['path'] for e in m['place'] if (F / e['path']).exists() and sha(F / e['path']) != e['sha256']]
    res['conflicts'] = conf
    cur = {e['path']: (sha(F / e['path']) if (F / e['path']).is_file() else None) for e in m['replace']}
    res['replace_current'] = {p: (v or 'MISSING')[:12] for p, v in cur.items()}
    res['replace_pre_switch'] = all(cur[e['path']] == e['old_sha256'] for e in m['replace'])
    res['replace_already'] = all(cur[e['path']] == e['sha256'] for e in m['replace'])
    res['ready'] = res['stage_sha_ok'] and res['replace_pre_switch'] and not conf
    return res

def apply(F, S, m, B=None):
    ov = Path(S) / 'formal_root_overlay'
    if B is not None:
        B.mkdir(parents=True, exist_ok=True)
        for i, e in enumerate(m['replace']): shutil.copy2(F / e['path'], B / f'before_{i}.json')
        (B / 'backup_manifest.json').write_text(json.dumps({'replace': [{'path': e['path'], 'sha256_before': e['old_sha256'], 'file': f'before_{i}.json'} for i, e in enumerate(m['replace'])]}, ensure_ascii=False, indent=2), encoding='utf-8')
    for e in m['place']:
        d = F / e['path']; d.parent.mkdir(parents=True, exist_ok=True)
        if not d.exists(): shutil.copy2(ov / e['path'], d)
        assert sha(d) == e['sha256'], e['path']
    for e in m['replace']:   # 順に: selector pointer → binding → Gate pointer（最後）。tmp+replace（ハードリンク先を壊さない）
        d = F / e['path']; tmp = d.with_name(d.name + '.switch_tmp'); shutil.copy2(ov / e['path'], tmp); os.replace(tmp, d)
        assert sha(d) == e['sha256'], e['path']

def restore(F, B):
    bm = json.loads((Path(B) / 'backup_manifest.json').read_text(encoding='utf-8')); ok = True
    for e in reversed(bm['replace']):
        d = F / e['path']; tmp = d.with_name(d.name + '.switch_tmp'); shutil.copy2(Path(B) / e['file'], tmp); os.replace(tmp, d)
        ok &= sha(d) == e['sha256_before']
    return ok

def compare(old, new, m):
    r = {}
    r['gate_old_ok'], r['gate_new_ok'] = old['gate']['ok'], new['gate']['ok']
    if old['gate']['ok'] and new['gate']['ok']:
        r['gate_rows_identical'] = old['gate']['rows'] == new['gate']['rows']
        r['gate_new_izumi'] = new['gate']['rows'].get('MUNI_272191')
    r['selector_old_ok'], r['selector_new_ok'] = old['selector']['ok'], new['selector']['ok']
    if old['selector']['ok'] and new['selector']['ok']:
        o, n = old['selector']['sel'], new['selector']['sel']
        diff = sorted(k for k in set(o) | set(n) if json.loads(o.get(k, '{}')).get('diagnostic') != json.loads(n.get(k, '{}')).get('diagnostic'))
        r['selector_changed'] = diff; r['selector_only_izumi'] = diff == m['changed_municipalities_slots']
        r['selector_count'] = [len(o), len(n)]
    r['binding_new'] = new['binding']
    r['binding_old'] = {'ok': old['binding']['ok']}
    pc = m['post_check']
    r['PASS'] = bool(r.get('gate_new_ok') and r.get('gate_rows_identical') and r.get('selector_only_izumi') and new['binding']['ok']
                     and sum(1 for _, s in new['binding'].get('izumi', []) if s == 'FILLED') == pc['izumi_selected']
                     and r.get('gate_new_izumi') == pc['izumi_gate'])
    return r

def clone(F, W):
    if W.exists(): shutil.rmtree(W)
    for p in F.rglob('*'):
        t = W / p.relative_to(F)
        if p.is_dir(): t.mkdir(parents=True, exist_ok=True); continue
        if '__pycache__' in p.parts: continue
        t.parent.mkdir(parents=True, exist_ok=True)
        try: os.link(p, t)
        except OSError: shutil.copy2(p, t)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('cmd', choices=['validate', 'switch', 'rollback'])
    ap.add_argument('--formal-root', required=True); ap.add_argument('--stage'); ap.add_argument('--work'); ap.add_argument('--backup')
    ap.add_argument('--execute', action='store_true'); ap.add_argument('--approval-ref')
    a = ap.parse_args(); F = Path(a.formal_root)
    if a.cmd == 'rollback':
        ok = restore(F, a.backup); print(json.dumps({'rolled_back': ok}, ensure_ascii=False)); sys.exit(0 if ok else 1)
    S = Path(a.stage); m = load_manifest(S); res = {'cmd': a.cmd}
    if a.cmd == 'validate':
        W = Path(a.work) / 'validate_root'; res['check_on_formal'] = check(F, S, m)
        old = probe(F); clone(F, W); apply(W, S, m); new = probe(W)
        res['compare'] = compare(old, new, m)
        (Path(a.work) / 'release_validation.json').write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(res, ensure_ascii=False, indent=2)); sys.exit(0 if res['compare']['PASS'] else 1)
    res.update(check(F, S, m)); res['mode'] = 'EXECUTE' if a.execute else 'DRY_RUN'
    if not (a.execute and res['ready']):
        print(json.dumps(res, ensure_ascii=False, indent=2)); sys.exit(0 if res['ready'] or res['replace_already'] else 1)
    if not a.approval_ref: print('--approval-ref が必要です'); sys.exit(2)
    B = F.parent / ('AIV_RELEASE_SWITCH_BACKUP_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    try:
        apply(F, S, m, B)
        (B / 'approval.txt').write_text(a.approval_ref, encoding='utf-8')
        new = probe(F); res['post_probe'] = {'gate': {k: v for k, v in new['gate'].items() if k != 'rows'}, 'selector_ok': new['selector']['ok'], 'binding': new['binding']}
        izu = new['gate'].get('rows', {}).get('MUNI_272191')
        assert new['gate']['ok'] and new['selector']['ok'] and new['binding']['ok'] and izu == m['post_check']['izumi_gate'], 'POST_CHECK_FAILED'
    except Exception as e:
        res['error'] = repr(e); res['auto_rollback_ok'] = restore(F, B) if (B / 'backup_manifest.json').exists() else None
        print(json.dumps(res, ensure_ascii=False, indent=2)); sys.exit(1)
    res['switched'] = True; res['backup'] = str(B); print(json.dumps(res, ensure_ascii=False, indent=2))
if __name__ == '__main__': main()
