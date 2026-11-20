"""R1 詳細版レポート レンダラ（T6 / マイルストーン M1: 表紙 + 16〜18 ページ）

values.json（T1 の出力）だけを入力に、HTML → Chrome headless → PDF で描画する。
- 値が VALUE 以外（null）のセルは「—」。データの補完・推計はしない。
- 内部確認用の下書き。納品物ではない（D-071/D-074）。
- フォント（Noto CJK, OFL）は PC の フォント フォルダから読み、Chrome のテキスト層が
  部首・互換文字に化けないよう cmap を整えた複製を作業フォルダに作って使う。
使い方:
  py scripts\\aiv_r1_render.py --values <values.json> --fonts <フォントフォルダ> --out <出力フォルダ>
"""
from __future__ import annotations
import argparse, html, json, pathlib, shutil, subprocess, sys

W, H = 595.247, 841.861
INK, SUB, MUTE, FAINT, NAVY, ACC, LINE, TINT = '#1E2A44', '#4A5568', '#5D6B80', '#7A8598', '#26397F', '#3B5BDB', '#D3DAE8', '#F2F5FD'
DASH = '—'
FONT_FILES = ['NotoSansCJKjp-Regular.otf', 'NotoSansCJKjp-Bold.otf', 'NotoSerifCJKjp-Regular.otf', 'NotoSerifCJKjp-Bold.otf']
STRIP = [(0x2E80, 0x2FDF), (0xF900, 0xFAFF), (0x2F800, 0x2FA1F), (0x2027, 0x2027), (0x2215, 0x2215)]
TOTAL_PAGES = 111
PURPOSES = ['PUR_01', 'PUR_02', 'PUR_03', 'PUR_04', 'PUR_05', 'PUR_06', 'PUR_07', 'PUR_08']
CHART_LABELS = {'PUR_01': '温泉', 'PUR_02': 'グルメ', 'PUR_03': '自然景観', 'PUR_04': '歴史文化', 'PUR_05': '都市観光',
                'PUR_06': 'TP等', 'PUR_07': '海マリン', 'PUR_08': '山岳等'}
e = html.escape


def patch_fonts(src: pathlib.Path, dst: pathlib.Path) -> None:
    from fontTools.ttLib import TTFont
    dst.mkdir(parents=True, exist_ok=True)
    for name in FONT_FILES:
        s = src / name
        if not s.exists():
            raise FileNotFoundError(f'フォントがありません: {s}')
        f = TTFont(str(s))
        for t in f['cmap'].tables:
            for cp in [c for c in list(t.cmap) if any(a <= c <= b for a, b in STRIP)]:
                del t.cmap[cp]
        f.save(str(dst / name))


def fmt_pct(v) -> str:
    """0〜1 の率 → 「24.0％」。None は「—」。"""
    return DASH if v is None else f'{v * 100:.1f}％'


class Page:
    def __init__(self):
        self.o: list[str] = []

    def t(self, x, y, s, size, color=INK, bold=False, serif=False, w=None, align='left', right=None):
        fam = 'S' if serif else 'N'
        pos = f'left:{x}pt;' if right is None else f'right:{W - right}pt;'
        wd = f'width:{w}pt;' if w else ''
        self.o.append(f'<div class="t" style="{pos}top:{y + 0.153 * size:.3f}pt;{wd}font:{"700" if bold else "400"} {size}pt/1 {fam};color:{color};text-align:{align}">{e(s)}</div>')

    def box(self, x0, y0, x1, y1, fill=None, border=None):
        st = f'left:{x0}pt;top:{y0}pt;width:{x1 - x0:.3f}pt;height:{y1 - y0:.3f}pt;'
        if fill: st += f'background:{fill};'
        if border: st += f'border:0.5pt solid {border};box-sizing:border-box;'
        self.o.append(f'<div style="position:absolute;{st}"></div>')

    def cc(self, xa, xb, y, s, size, color, bold=False):
        self.t(xa, y, s, size, color, bold=bold, w=xb - xa, align='center')

    def frame(self, report_id: str, issued: str, logo: str | None):
        self.box(23.7, 24.0, 571.5, 817.7, '#fff', LINE)
        self.box(40, 72, 555.3, 72.5, LINE); self.box(40, 794.4, 555.3, 794.8, LINE)
        if logo:
            self.o.append(f'<img src="{logo}" style="position:absolute;left:35.1pt;top:35.3pt;width:141.7pt;height:26.4pt">')
        self.t(0, 40, f'Report ID：{report_id}', 7.5, FAINT, right=555.3)
        self.t(0, 53, f'発行日：{issued}', 7.5, FAINT, right=555.3)

    def footer(self, left: str, n: int):
        self.t(40, 801, left, 6.2, FAINT); self.t(0, 801, f'{n} / {TOTAL_PAGES}', 6.2, FAINT, right=555.4)

    def sect(self, y, label, tab):
        self.box(40, y - 2.8, 43, y + 7.9, ACC)
        self.t(48.3, y, label, 9.6, NAVY, bold=True)
        if tab: self.t(0, y + 5, tab, 6.2, MUTE, right=555.4)

    def table(self, x0, y0, widths, hh, rh):
        xs = [x0]
        for w in widths: xs.append(xs[-1] + w)
        tot = xs[-1] - x0; ytot = y0 + hh + sum(rh)
        self.box(x0 - 0.3, y0 - 0.2, x0 + tot + 0.3, ytot + 0.2, '#fff', LINE)
        self.box(x0, y0 + 0.2, x0 + tot, y0 + hh, TINT)
        self.box(x0, y0 + hh, xs[1], ytot - 0.2, TINT)
        self.box(x0, y0 + 0.2, x0 + 3, ytot - 0.2, ACC)
        y = y0 + hh
        self.box(x0, y - 0.3, x0 + tot, y + 0.2, LINE)
        for r in rh[:-1]:
            y += r; self.box(x0, y - 0.25, x0 + tot, y + 0.25, LINE)
        for xx in xs[1:-1]: self.box(xx - 0.25, y0 + 0.2, xx + 0.25, ytot - 0.2, LINE)
        return xs

    def html(self) -> str:
        return '<div class="page">' + ''.join(self.o) + '</div>'


class Ctx:
    def __init__(self, values: dict, issued: str = DASH, report_id: str = DASH, provisional: bool = False):
        self.provisional = provisional   # 仮: ChatGPT の値を AI3種平均の代わりに使う（内部確認用）
        self.v = values; self.s = values['slots']; self.m = values['meta']
        self.name = self.m['name']; self.pref = self.m['prefecture']
        self.block = self.m['region_block_name'].replace('地方', 'ブロック')
        self.report_id, self.issued = report_id, issued

    def val(self, slot: str):
        x = self.s.get(slot)
        return None if x is None or x.get('status') not in ('VALUE', 'EXPLICIT_ZERO') else x['value']

    def pop(self, tier: str):
        key = {'national': 'G03.rank.national', 'region_block': 'G03.rank.region_block', 'prefecture': 'G03.rank.prefecture'}[tier]
        return (self.s.get(key) or {}).get('population')


def wrap_names(names: list, width_chars: int = 21, max_lines: int = 2) -> list:
    """区分名を「／」で連ねて width_chars（全角換算）で折り返す。入り切らない分は「ほか N区分」。"""
    lines, cur, i = [], '', 0
    while i < len(names):
        nxt = names[i] if not cur else cur + '／' + names[i]
        if len(nxt) <= width_chars or not cur:
            cur = nxt; i += 1
        else:
            lines.append(cur); cur = ''
            if len(lines) == max_lines: break
    if cur and len(lines) < max_lines: lines.append(cur); cur = ''
    rest = len(names) - sum(l.count('／') + 1 for l in lines)
    if rest > 0:
        tail = f'ほか {rest}区分'
        lines[-1] = lines[-1] if len(lines[-1]) + len(tail) + 1 <= width_chars else lines[-1]
        lines[-1] += '／' + tail if len(lines[-1]) + len(tail) + 1 <= width_chars else ''
        if not lines[-1].endswith(tail) and len(lines) < max_lines: lines.append(tail)
    return lines


TREND_TEXT = {'中核': '対象地域の中核的な訴求軸として AI 上に定着している。',
              '準中核': '認識はあるが、上位競合との差が生じやすい領域。',
              '弱': '資源の有無と情報発信量の双方に課題がある。'}


def trend_class(v: float) -> str:
    """仮の区分（T4 の分類方式が決まるまで）: 20％以上＝中核、5％以上＝準中核、それ未満＝弱。見本の 3 区分と矛盾しない値。"""
    return '中核' if v >= 0.20 else '準中核' if v >= 0.05 else '弱'


def provisional_series(c: 'Ctx', tier: str):
    """[(pid, 値 or None)]。仮モードでのみ値を返す（ChatGPT の値＝AI3種平均の仮置き）。"""
    return [(pid, c.val(f'G03.category.{pid}.{tier}') if c.provisional else None) for pid in PURPOSES]


TIERS = {
    'national': dict(page=16, base='全国基準', sects=('Ⅱ-1', 'Ⅱ-2', 'Ⅱ-3'), tabs=('表 21', '表 22')),
    'region_block': dict(page=17, base=None, sects=('Ⅱ-4', 'Ⅱ-5', 'Ⅱ-6'), tabs=('表 23', '表 24')),
    'prefecture': dict(page=18, base=None, sects=('Ⅱ-7', 'Ⅱ-8', 'Ⅱ-9'), tabs=('表 25', '表 26')),
}


def tier_text(c: Ctx, tier: str):
    n = c.pop(tier)
    ns = f'{n:,}' if isinstance(n, int) else DASH
    if tier == 'national': return '全国基準', f'全国 {ns} 自治体'
    if tier == 'region_block': return f'{c.block}基準', f'{ns} 自治体'
    return f'{c.pref}基準', f'{c.pref} {ns} 市町村'


def page_footer(c: Ctx) -> str:
    return f'AI 可視性分析レポート ／ {c.pref} {c.name} ｜ ② 出現率分析'


def render_purpose_page(c: Ctx, tier: str, logo) -> Page:
    cfg = TIERS[tier]; base, pop = tier_text(c, tier)
    p = Page(); p.frame(c.report_id, c.issued, logo)
    p.t(40, 93, f'②-Ⅱ. 旅行目的別 出現率（{base}）', 14.2, INK, serif=True)
    p.t(40, 114, f'旅行目的 8区分について、{base}における AI 別の出現率は以下のとおりです。', 8.2, SUB)
    p.sect(141, f'{cfg["sects"][0]}. 旅行目的 × AI別 出現率（{base}）', cfg['tabs'][0])
    xs = p.table(40, 155.5, [155.3, 75.6, 75.6, 75.6, 75.6, 57.6], 18.7, [17.65] * 8)
    heads = ['旅行目的', 'ChatGPT', 'Gemini', 'Claude', '平均', '前回比']
    p.t(47.2, 162, heads[0], 7.8, NAVY, bold=True)
    for i in range(1, 6): p.cc(xs[i], xs[i + 1], 162, heads[i], 7.8, NAVY, True)
    for k, pid in enumerate(PURPOSES):
        y = 181 + k * 17.65
        slot = c.s.get(f'G03.category.{pid}.{tier}', {})
        p.t(46.5, y, slot.get('label') or pid, 7.4, INK)
        v = c.val(f'G03.category.{pid}.{tier}')
        cells = [fmt_pct(v), DASH, DASH, fmt_pct(v) if c.provisional else DASH, DASH]   # Gemini/Claude/前回比は未測定。平均は仮モードのみ ChatGPT 値
        for i, s in enumerate(cells, 1): p.cc(xs[i], xs[i + 1], y, s, 7.4, INK)
    p.t(40, 335, '※ 前回比は初回測定のため算出していません。', 6.2, MUTE)   # 差し替え文: 社長確認待ち
    p.sect(358, f'{cfg["sects"][1]}. 旅行目的別 出現率（AI3種平均）', '')
    p.box(39.7, 372.8, 555.6, 577.9, '#fff', LINE)
    ser = provisional_series(c, tier)
    have = [(pid, v) for pid, v in ser if v is not None]
    mx = max([v for _, v in have], default=0)
    if mx <= 0.30: n_int, step = 6, 5
    else: n_int, step = 5, 20
    ax_max = n_int * step; gw = 453.0 / n_int; ppu = 453.0 / ax_max   # pt / (％ 1 ポイント)
    for k in range(n_int + 1):
        xx = 84.4 + k * gw; p.box(xx - 0.25, 382.6, xx + 0.25, 556.6, LINE)
        p.t(xx - 8, 562, str(k * step), 6.6, FAINT, w=16, align='center')
    order = sorted(ser, key=lambda x: (-(x[1] if x[1] is not None else -1), PURPOSES.index(x[0]))) if have else [(pid, None) for pid in ['PUR_08', 'PUR_03', 'PUR_01', 'PUR_02', 'PUR_04', 'PUR_06', 'PUR_05', 'PUR_07']]
    for k, (pid, v) in enumerate(order):
        p.t(0, 391 + k * 21.75, CHART_LABELS[pid], 6.6, SUB, right=81.4)
        if v is not None:
            wbar = v * 100 * ppu
            if wbar > 0.2: p.box(84, 386 + k * 21.75, 84 + wbar, 386 + k * 21.75 + 14, ACC)
            p.t(84 + wbar + 3, 391 + k * 21.75, f'{v * 100:.1f}%', 6.4, SUB)
    p.t(40, 587, f'※ {base}（母集団：{pop}）における値。旅行目的を指定した質問群での出現割合。', 6.2, MUTE)
    hi = lo = DASH
    if have:
        top = max(v for _, v in have); bot = min(v for _, v in have)
        tops = [pid for pid, v in have if v == top]; bots = [pid for pid, v in have if v == bot]
        hi = (f'{CHART_LABELS[tops[0]]}（{top * 100:.1f}％）' if len(tops) == 1 else f'{len(tops)}区分が同率（{top * 100:.1f}％）')
        lo = (f'{CHART_LABELS[bots[0]]}（{bot * 100:.1f}％）' if len(bots) == 1 else f'{len(bots)}区分が同率（{bot * 100:.1f}％）')
    for x0, x1, a, c0, txt in ((40, 292.2, '最も高い旅行目的', 52, hi), (303.1, 555.3, '最も低い旅行目的', 315, lo)):
        p.box(x0, 608.4, x1, 630, TINT); p.box(x0, 608.4, x0 + 3, 630, ACC)
        p.t(c0, 617, a, 7.6, NAVY, bold=True); p.t(c0 + 93.6, 617, txt, 8.2, INK)
    p.sect(645, f'{cfg["sects"][2]}. 旅行目的別の傾向', cfg['tabs'][1])
    xs2 = p.table(40, 660.2, [61.7, 176.4, 277.7], 18.7, [24.9] * 3)
    p.t(62.8, 667, '区分', 7.8, NAVY, bold=True); p.t(108.4, 667, '該当旅行目的', 7.8, NAVY, bold=True); p.t(284.8, 667, '傾向', 7.8, NAVY, bold=True)
    for k, cls in enumerate(['中核', '準中核', '弱']):
        y = 689 + k * 24.8
        names = [CHART_LABELS[pid] for pid, v in order if v is not None and trend_class(v) == cls]
        p.cc(xs2[0], xs2[1], y, cls, 7.4, INK)
        lines = wrap_names(names) if names else [DASH if not have else 'なし']
        for li, ln in enumerate(lines):
            p.t(107.7, y - (3.6 if len(lines) == 2 else 0) + li * 7.8, ln, 7.4, INK)
        p.t(284.1, y, TREND_TEXT[cls] if names else DASH, 7.4, INK)
    if c.provisional:
        p.t(40, 780, '【仮・内部確認用】ChatGPT の値のみを「平均」「AI3種平均」の代わりに表示。Gemini・Claude は未測定。区分（中核・準中核・弱）は仮の基準（20％以上／5％以上／未満）。', 6.2, '#B42318')
    p.footer(page_footer(c), cfg['page'])
    return p


def render_cover(c: Ctx, logo) -> Page:
    p = Page()
    p.box(0, 0, W, H, '#fff')
    p.box(23.7, 24.0, 571.5, 817.7, '#fff', LINE)
    p.box(248.4, 313.9, 346.8, 314.4, LINE); p.box(106.3, 561.7, 489.0, 562.2, LINE); p.box(106.3, 632.2, 489.0, 632.7, LINE)
    for xx in (193.7, 324.3, 414.6): p.box(xx, 567.5, xx + 0.5, 626.5, LINE)
    p.box(40, 710.6, 555.3, 711.1, LINE)
    mid = W / 2
    p.cc(0, W, 178.6, 'AI VISIBILITY REPORT', 11, NAVY, serif=False) if False else p.t(0, 178.6, 'AI VISIBILITY REPORT', 11, NAVY, serif=True, w=W, align='center')
    p.t(0, 236.8, 'AI 可視性分析レポート', 30, INK, serif=True, w=W, align='center')
    p.t(0, 357.2, f'{c.pref} {c.m.get("county") or ""}'.strip(), 11, SUB, w=W, align='center')
    p.t(0, 413.4, c.name, 27, INK, serif=True, w=W, align='center')
    p.t(0, 472.7, DASH, 8, FAINT, w=W, align='center')   # 英語名: 未確認のため「—」
    heads = [(106.3, 193.7, '測定対象'), (193.7, 324.3, '対象 AI'), (324.3, 414.6, '測定日'), (414.6, 489.0, '投入質問数')]
    for a, b, s in heads: p.cc(a, b, 581.6, s, 7.6, NAVY, True)
    vals = [f'{c.pref} {c.name}', 'ChatGPT', c.m.get('measurement_period') or DASH, DASH]
    for (a, b, _), s in zip(heads, vals): p.cc(a, b, 605.8, s, 8.4, INK)
    p.t(40, 735, f'Report ID：{c.report_id}', 7.8, FAINT); p.t(40, 747, f'発行日：{c.issued}', 7.8, FAINT)
    p.t(40, 759, f'測定期間：{c.m.get("measurement_period") or DASH}', 7.8, FAINT)
    p.t(0, 735, 'AI Visibility Japan 株式会社', 7.8, FAINT, right=555.3)
    p.t(0, 747, DASH, 7.8, FAINT, right=555.3); p.t(0, 759, f'TEL：{DASH}', 7.8, FAINT, right=555.3)
    if logo:
        p.o.append(f'<img src="{logo}" style="position:absolute;left:{mid - 70.85}pt;top:80pt;width:141.7pt;height:26.4pt">')
    return p


def build_html(c: Ctx, fonts_uri: pathlib.Path, logo: str | None) -> str:
    pages = [(1, render_cover(c, logo))] + [(TIERS[t]['page'], render_purpose_page(c, t, logo)) for t in ('national', 'region_block', 'prefecture')]
    css = ''.join(f'@font-face{{font-family:{fam};font-weight:{w};src:url("{(fonts_uri / f).as_uri()}")}}\n' for fam, w, f in
                  [('N', 400, FONT_FILES[0]), ('N', 700, FONT_FILES[1]), ('S', 400, FONT_FILES[2]), ('S', 700, FONT_FILES[3])])
    css += (f'@page{{size:{W}pt {H}pt;margin:0}} html,body{{margin:0;padding:0;background:#fff}}'
            f'.page{{position:relative;width:{W}pt;height:{H}pt;overflow:hidden;break-after:page}}'
            '.t{position:absolute;white-space:nowrap;font-kerning:none}')
    return f'<!doctype html><html lang="ja"><meta charset="utf-8"><style>{css}</style><body>{"".join(p.html() for _, p in pages)}</body></html>'


def find_chrome() -> str:
    for cand in ('google-chrome', 'chromium', 'chrome', r'C:\Program Files\Google\Chrome\Application\chrome.exe',
                 r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
                 r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', r'C:\Program Files\Microsoft\Edge\Application\msedge.exe'):
        if shutil.which(cand) or pathlib.Path(cand).exists(): return shutil.which(cand) or cand
    raise RuntimeError('Chrome / Edge が見つかりません')


def render(values_path: pathlib.Path, fonts: pathlib.Path, out: pathlib.Path, logo: pathlib.Path | None = None, provisional: bool = False) -> pathlib.Path:
    values_path, fonts, out = values_path.resolve(), fonts.resolve(), out.resolve()
    logo = logo.resolve() if logo else None
    values = json.loads(values_path.read_text(encoding='utf-8'))
    c = Ctx(values, provisional=provisional)
    if out.exists() and any(out.iterdir()): raise FileExistsError(f'出力先が空ではありません: {out}')
    out.mkdir(parents=True, exist_ok=True)
    patch_fonts(fonts, out / 'fonts')
    logo_name = None
    if logo and logo.exists(): shutil.copy(logo, out / 'logo.png'); logo_name = 'logo.png'
    (out / 'report.html').write_text(build_html(c, out / 'fonts', logo_name), encoding='utf-8')
    pdf = out / f'下書き_{c.name}_M1{"_仮" if provisional else ""}.pdf'
    subprocess.run([find_chrome(), '--headless', '--disable-gpu', '--no-pdf-header-footer', f'--print-to-pdf={pdf}',
                    (out / 'report.html').as_uri()], check=True, timeout=180)
    return pdf


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--values', required=True, type=pathlib.Path); ap.add_argument('--fonts', required=True, type=pathlib.Path)
    ap.add_argument('--out', required=True, type=pathlib.Path); ap.add_argument('--logo', type=pathlib.Path)
    ap.add_argument('--provisional', action='store_true', help='仮: ChatGPT の値を AI3種平均の代わりに表示（内部確認用）')
    a = ap.parse_args(argv)
    print(render(a.values, a.fonts, a.out, a.logo, a.provisional)); return 0


if __name__ == '__main__':
    sys.exit(main())
