#!/usr/bin/env python3
"""Gate新版stage READ-ONLY 実ファイル検証.
正式ルートは読むだけ(書込なし)。stageを重ねた一時ルートを --work に作り、新旧アダプタを実行して
全自治体の判定差分を出す。使い方:
  python aiv_gate_stage_validate.py --formal-root "<正式ルート>" --stage "<Gate新版stage_20261114>" --work "<一時作業先>"
"""
import argparse, csv, hashlib, json, os, shutil, subprocess, sys
from pathlib import Path

G = Path('03_実行基盤・コード/03_診断レポート/現行レポート基盤/03_generated')
RUNNER = r'''
import sys, json, importlib
sys.dont_write_bytecode = True
scripts, mod, cls = sys.argv[1:4]
sys.path.insert(0, scripts)
m = importlib.import_module(mod)
try:
    a = getattr(m, cls)()
    out = {'ok': True, 'status': a.validation['status'], 'source_count': a.validation['source_count'],
           'rows': {k: [v.get('preflight_result'), v.get('report_generation_allowed'), v.get('unreviewed_concrete_candidate')] for k, v in a.status_by_municipality.items()}}
except Exception as e:
    out = {'ok': False, 'error': repr(e), 'detail': getattr(e, 'args', None) and [str(x) for x in e.args]}
print(json.dumps(out, ensure_ascii=False))
'''

def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()

def jload(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))

def mirror(src_root, dst_root, rel, miss):
    s = src_root / rel
    if not s.is_file(): miss.append(str(rel)); return
    d = dst_root / rel; d.parent.mkdir(parents=True, exist_ok=True)
    if d.exists(): return
    try: os.link(s, d)
    except OSError: shutil.copy2(s, d)

def run(scripts, mod, cls, env_extra=None):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
    r = subprocess.run([sys.executable, '-I', '-c', RUNNER, str(scripts), mod, cls], capture_output=True, text=True, encoding='utf-8', env=env)
    try: return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception: return {'ok': False, 'error': 'RUNNER_FAILED', 'detail': (r.stderr or r.stdout)[-1500:]}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--formal-root', required=True); ap.add_argument('--stage', required=True); ap.add_argument('--work', required=True)
    a = ap.parse_args()
    F, S, W = Path(a.formal_root), Path(a.stage), Path(a.work)
    man = jload(S / 'manifest.json'); ov = S / 'formal_root_overlay'
    contract = jload(ov / man['contract']['path'])
    # integrity of stage files against manifest
    chk = {k: sha(ov / man[k]['path']) == man[k]['sha256'] for k in ['status', 'contract', 'config', 'runtime', 'launcher', 'pointer']}
    miss = []
    R = W / 'validate_root'
    if R.exists(): shutil.rmtree(R)
    R.mkdir(parents=True)
    for r in contract['sources']:
        if r['logical_source_name'] == 'gate_municipality_status': continue
        v = r['path_relative_to_formal_root']
        if not Path(v).is_absolute(): mirror(F, R, Path(v), miss)
    for m in contract['bound_manifests']:
        mirror(F, R, Path(m['path']), miss)
        p = F / m['path']
        if p.is_file():
            md = jload(p)
            for k, v in md.items():
                if k.endswith('_path') and isinstance(v, str) and not Path(v).is_absolute(): mirror(F, R, Path(v), miss)
    cfg = G / 'config'
    sp = cfg / 'diagnostic_resource_selector_formal_current.json'; mirror(F, R, sp, miss)
    if (F / sp).is_file():
        d = jload(F / sp)
        if d.get('pin_path'):
            mirror(F, R, Path(d['pin_path']), miss)
            if (F / d['pin_path']).is_file():
                pd = jload(F / d['pin_path'])
                for k in ('selector_config_path', 'launcher_path'):
                    if pd.get(k): mirror(F, R, Path(pd[k]), miss)
    mirror(F, R, G / 'scripts/aiv_resource_coverage_preflight_v1_1_8.py', miss)
    mirror(F, R, cfg / 'resource_coverage_preflight_v1_1_8.json', miss)
    # overlay (stage = new Gate)
    for k in ['status', 'contract', 'config', 'runtime', 'launcher', 'pointer']:
        d = R / man[k]['path']; d.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(ov / man[k]['path'], d)
    # old = real formal root (read-only), new = temp root
    old_ptr = jload(F / G / 'config/resource_coverage_preflight_formal_current.json')
    old_rt = Path(old_ptr['runtime_script']).stem
    old = run(F / G / 'scripts', old_rt, 'ResourceCoveragePreflightSourceContractV119')
    new = run(R / G / 'scripts', 'aiv_resource_coverage_preflight_source_contract_v1_1_10', 'ResourceCoveragePreflightSourceContractV1110')
    res = {'stage_sha_ok': chk, 'mirror_missing': miss, 'old_ok': old.get('ok'), 'new_ok': new.get('ok'),
           'old': {k: v for k, v in old.items() if k != 'rows'}, 'new': {k: v for k, v in new.items() if k != 'rows'}}
    if old.get('ok') and new.get('ok'):
        o, n = old['rows'], new['rows']
        diff = sorted(k for k in set(o) | set(n) if o.get(k) != n.get(k))
        res.update(rows_old=len(o), rows_new=len(n), changed=diff,
                   allowed_old=sum(1 for v in o.values() if v[1] == 'TRUE'), allowed_new=sum(1 for v in n.values() if v[1] == 'TRUE'),
                   only_izumi=(diff == ['MUNI_272191']), izumi_new=n.get('MUNI_272191'))
        with open(W / 'gate_diff.csv', 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f); w.writerow(['municipality_id', 'old', 'new'])
            for k in diff: w.writerow([k, o.get(k), n.get(k)])
    (W / 'stage_validation.json').write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(res, ensure_ascii=False, indent=2))
if __name__ == '__main__': main()
