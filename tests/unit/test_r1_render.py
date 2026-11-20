"""R1 レンダラ（T6 M1）の単体試験：値の表示規則（VALUE 以外は「—」）と固定文。Chrome は使わない。"""
import importlib.util, pathlib, sys
_p = pathlib.Path(__file__).resolve().parents[2] / 'scripts' / 'aiv_r1_render.py'
_s = importlib.util.spec_from_file_location('aiv_r1_render', _p); r = importlib.util.module_from_spec(_s); sys.modules['aiv_r1_render'] = r; _s.loader.exec_module(r)


def _values():
    s = {f'G03.category.PUR_0{i}.{t}': {'status': 'VALUE', 'value': 0.1 * i, 'label': f'区分{i}'} for i in range(1, 9) for t in ('national', 'region_block', 'prefecture')}
    s['G03.category.PUR_02.national'] = {'status': 'NOT_MEASURED', 'value': None, 'label': '区分2'}
    s['G03.category.PUR_03.national'] = {'status': 'EXPLICIT_ZERO', 'value': 0.0, 'label': '区分3'}
    s['G03.rank.national'] = {'population': 1741}; s['G03.rank.region_block'] = {'population': 198}; s['G03.rank.prefecture'] = {'population': 30}
    return {'meta': {'name': 'テスト町', 'prefecture': 'テスト県', 'region_block_name': '近畿地方', 'measurement_period': '2026年9月1日～9月30日'}, 'slots': s}


def test_fmt_pct():
    assert r.fmt_pct(None) == '—' and r.fmt_pct(0.0) == '0.0％' and r.fmt_pct(0.24) == '24.0％'


def test_non_value_is_dash_and_zero_is_zero():
    c = r.Ctx(_values()); h = r.render_purpose_page(c, 'national', None).html()
    assert '0.0％' in h and 'NOT_MEASURED' not in h
    assert c.val('G03.category.PUR_02.national') is None and c.val('G03.category.PUR_03.national') == 0.0


def test_tier_texts_and_no_fabricated_ids():
    c = r.Ctx(_values())
    assert r.tier_text(c, 'national') == ('全国基準', '全国 1,741 自治体')
    assert r.tier_text(c, 'region_block')[0] == '近畿ブロック基準'
    h = r.build_html(c, pathlib.Path('.').resolve(), None)
    assert 'AIV-SNP' not in h and '雪嶺' not in h and 'Report ID：—' in h and '16 / 111' in h and '18 / 111' in h


def test_relative_paths_are_resolved(tmp_path, monkeypatch):
    """相対パス指定でも @font-face の file URI を作れる（実機で出た不具合の再発防止）。"""
    import os
    monkeypatch.chdir(tmp_path)
    p = pathlib.Path('fonts'); h = r.build_html(r.Ctx(_values()), p.resolve(), None)
    assert 'file:///' in h


def test_provisional_mode_fills_average_only_when_requested():
    off = r.render_purpose_page(r.Ctx(_values()), 'national', None).html()
    on = r.render_purpose_page(r.Ctx(_values(), provisional=True), 'national', None).html()
    assert '【仮・内部確認用】' in on and '【仮・内部確認用】' not in off
    assert r.trend_class(0.25) == '中核' and r.trend_class(0.10) == '準中核' and r.trend_class(0.01) == '弱'
    assert r.provisional_series(r.Ctx(_values()), 'national')[0][1] is None


def test_wrap_names_fits_two_lines_and_keeps_all_names():
    names = ['温泉', 'グルメ', '自然景観', '歴史文化', '都市観光', 'TP等', '海マリン', '山岳等']
    ls = r.wrap_names(names)
    assert len(ls) <= 2 and all(len(l) <= 21 for l in ls)
    joined = '／'.join(ls)
    shown = sum(1 for n in names if n in joined)
    assert shown + (int(joined.split('ほか ')[1].split('区分')[0]) if 'ほか ' in joined else 0) == len(names)
