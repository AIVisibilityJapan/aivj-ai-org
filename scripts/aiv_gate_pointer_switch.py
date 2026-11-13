#!/usr/bin/env python3
"""Gate current pointer 切替ツール（確認②）。既定は --dry-run（何も書かない）。
  検査のみ : python aiv_gate_pointer_switch.py --formal-root "<正式ルート>" --stage "<Gate新版stage>"
  切替実行 : 上記 + --execute --approval-ref <社長確認の参照>
  戻し     : python aiv_gate_pointer_switch.py --formal-root "<正式ルート>" --rollback "<backupフォルダ>"
手順: stage SHA検査 → 現行pointerが切替前(manifest _old_sha256.pointer)か検査 → backup作成 →
      新ファイル5本を配置(既存と異なる内容なら中止) → pointerを最後に原子的に差替え → 切替後検証 → 失敗なら自動で戻す。
"""
import argparse, hashlib, json, os, shutil, subprocess, sys, datetime
from pathlib import Path

def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()

ORDER = ['status', 'contract', 'config', 'runtime', 'launcher']  # pointer は最後

CHECK = r'''
import sys, json, importlib
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1]); m = importlib.import_module(sys.argv[2])
a = getattr(m, sys.argv[3])()
rows = a.status_by_municipality
print(json.dumps({'ok': True, 'status': a.validation['status'], 'rows': len(rows),
  'allowed': sum(1 for v in rows.values() if v.get('report_generation_allowed') == 'TRUE'),
  'izumi': [rows['MUNI_272191'].get('preflight_result'), rows['MUNI_272191'].get('report_generation_allowed')]}))
'''

def post_check(F):
    G = F / '03_実行基盤・コード/03_診断レポート/現行レポート基盤/03_generated'
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
    p = json.loads((G / 'config/resource_coverage_preflight_formal_current.json').read_text(encoding='utf-8-sig'))
    mod = Path(p['runtime_script']).stem
    cls = 'ResourceCoveragePreflightSourceContractV1110' if mod.endswith('1_1_10') else 'ResourceCoveragePreflightSourceContractV119'
    r = subprocess.run([sys.executable, '-I', '-c', CHECK, str(G / 'scripts'), mod, cls], capture_output=True, text=True, encoding='utf-8', env=env)
    try: return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception: return {'ok': False, 'detail': (r.stderr or r.stdout)[-1200:]}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--formal-root', required=True); ap.add_argument('--stage'); ap.add_argument('--rollback')
    ap.add_argument('--execute', action='store_true'); ap.add_argument('--approval-ref'); ap.add_argument('--skip-post-check', action='store_true')
    a = ap.parse_args(); F = Path(a.formal_root)
    if a.rollback:
        B = Path(a.rollback); bm = json.loads((B / 'backup_manifest.json').read_text(encoding='utf-8'))
        dst = F / bm['pointer_path']; shutil.copy2(B / 'pointer_before.json', dst)
        ok = sha(dst) == bm['pointer_sha256_before']; print(json.dumps({'rolled_back': ok, 'pointer_sha256': sha(dst)}, ensure_ascii=False)); sys.exit(0 if ok else 1)
    S = Path(a.stage); man = json.loads((S / 'manifest.json').read_text(encoding='utf-8')); ov = S / 'formal_root_overlay'
    res = {'mode': 'EXECUTE' if a.execute else 'DRY_RUN'}
    res['stage_sha_ok'] = {k: sha(ov / man[k]['path']) == man[k]['sha256'] for k in ORDER + ['pointer']}
    cur = F / man['pointer']['path']; cur_sha = sha(cur) if cur.is_file() else None
    res['current_pointer_sha'] = cur_sha; res['expected_before'] = man['_old_sha256']['pointer']
    res['already_switched'] = cur_sha == man['pointer']['sha256']
    res['pointer_is_pre_switch'] = cur_sha == man['_old_sha256']['pointer']
    conflicts = []
    for k in ORDER:
        d = F / man[k]['path']
        if d.exists() and sha(d) != man[k]['sha256']: conflicts.append(man[k]['path'])
    res['conflicts'] = conflicts
    ready = all(res['stage_sha_ok'].values()) and res['pointer_is_pre_switch'] and not conflicts
    res['ready'] = ready
    if not a.execute or not ready:
        print(json.dumps(res, ensure_ascii=False, indent=2)); sys.exit(0 if (ready or res['already_switched']) else 1)
    if not a.approval_ref: print('--approval-ref が必要です'); sys.exit(2)
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    B = F.parent / f'AIV_GATE_SWITCH_BACKUP_{ts}'; B.mkdir(parents=True)
    shutil.copy2(cur, B / 'pointer_before.json')
    (B / 'backup_manifest.json').write_text(json.dumps({'pointer_path': man['pointer']['path'], 'pointer_sha256_before': cur_sha, 'approval_ref': a.approval_ref, 'stage': str(S)}, ensure_ascii=False, indent=2), encoding='utf-8')
    placed = []
    try:
        for k in ORDER:
            d = F / man[k]['path']; d.parent.mkdir(parents=True, exist_ok=True)
            if not d.exists(): shutil.copy2(ov / man[k]['path'], d); placed.append(d)
            assert sha(d) == man[k]['sha256'], k
        tmp = cur.with_suffix('.json.switch_tmp'); shutil.copy2(ov / man['pointer']['path'], tmp); os.replace(tmp, cur)
        assert sha(cur) == man['pointer']['sha256']
        if not a.skip_post_check:
            pc = post_check(F); res['post_check'] = pc
            assert pc.get('ok') and pc.get('izumi') == ['RESOURCE_PREFLIGHT_PASS', 'TRUE'], 'POST_CHECK_FAILED'
    except Exception as e:
        shutil.copy2(B / 'pointer_before.json', cur)
        res['error'] = repr(e); res['auto_rollback_pointer_ok'] = sha(cur) == cur_sha
        print(json.dumps(res, ensure_ascii=False, indent=2)); sys.exit(1)
    res['switched'] = True; res['backup'] = str(B)
    print(json.dumps(res, ensure_ascii=False, indent=2))
if __name__ == '__main__': main()
