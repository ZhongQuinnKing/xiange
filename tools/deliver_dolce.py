#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交付链·简谱腿：MusicXML -> 悦谱 Dolce（本地）-> 简谱矢量 PDF/PNG + 123 文本

依赖：
  - 悦谱 Dolce 仓库（MIT，github.com/lodebar2026/dolce；浏览器版，本地起 dev server）
    仓库位置用环境变量 DOLCE_DIR 指定（默认 ~/dolce）
  - playwright（无头浏览器驱动）、cairosvg
  - Node/npm（起 dev server 用；未起时本脚本自动起，跑完保持）

用法:
  python3 deliver_dolce.py --xml <输入.musicxml> --out <输出目录> [--view printed]
  python3 deliver_dolce.py --batch <输入目录> --out <输出目录> [--view printed]

产出（每件）:
  <名>_pN.svg / <名>_pN.pdf / <名>_pN.png   简谱页面（矢量）
  <名>.123.txt                              转换出的 123 源码文本

已知限制（2026-10-10 实测）:
  - 单声部 MusicXML 才会进简谱档；多声部直接进五线谱/混排视图，本脚本跳过并标注
  - 多页长谱：视图中未渲染的页可能抽不到 [?]（当前测试件均为单页）
"""
import argparse
import glob
import os
import subprocess
import sys
import time
import urllib.request

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # 无浏览器档时不崩在 import，由 main 守卫拒跑
    sync_playwright = None
try:
    import cairosvg
except ImportError:
    cairosvg = None

DOLCE_DIR = os.environ.get('DOLCE_DIR', os.path.expanduser('~/dolce'))
PORT = int(os.environ.get('DOLCE_PORT', '5188'))
BASE = f'http://localhost:{PORT}/'

JS_OK = '''() => {
  const okTexts = ['OK', '确定', '好', '是'];
  const btns = [...document.querySelectorAll('button')].filter(b => b.offsetParent !== null);
  const b = btns.find(x => okTexts.includes(x.textContent.trim()));
  if (b) { b.click(); return b.textContent.trim(); }
  return 'none';
}'''

JS_CLICK = '''(t) => {
  const btns = [...document.querySelectorAll('button')].filter(b => b.offsetParent !== null);
  const b = btns.find(x => x.textContent.trim() === t);
  if (b) { b.click(); return true; }
  return false;
}'''


def server_up():
    try:
        with urllib.request.urlopen(BASE, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def ensure_server():
    if server_up():
        return '已在运行'
    subprocess.Popen(
        ['npm', 'run', 'dev', '--', '--port', str(PORT), '--strictPort'],
        cwd=DOLCE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        time.sleep(1.5)
        if server_up():
            return '已自动启动'
    raise RuntimeError('dev server 起不来：手动检查 ' + DOLCE_DIR)


def drain_dialogs(pg, tries=5):
    for _ in range(tries):
        pg.wait_for_timeout(1200)
        if pg.evaluate(JS_OK) == 'none':
            return
    print('  警告：弹窗未清空')


def open_score(pg, xml_path):
    """Home 页导入：优先英文按钮，回落中文文案。"""
    clicked = pg.evaluate('''() => {
      const wanted = ['Open score', '打开曲谱', '打开乐谱'];
      const els = [...document.querySelectorAll('button, a, div[role="button"], .card, [class*="card"]')]
        .filter(e => e.offsetParent !== null);
      const el = els.find(e => wanted.includes((e.innerText || '').trim()));
      if (el) { el.click(); return true; }
      return false;
    }''')
    if not clicked:
        # 回落：Playwright 文本定位触发文件选择器
        pg.get_by_text('Open score', exact=True).first.click()
        return
    # JS 点击后文件选择器同样会弹出，交给调用方 expect_file_chooser 捕获
    pg.wait_for_timeout(300)


def convert_file(pg, xml_path, outdir, view):
    stem = os.path.splitext(os.path.basename(xml_path))[0]
    pg.goto(BASE, wait_until='domcontentloaded')
    pg.wait_for_timeout(2500)
    with pg.expect_file_chooser(timeout=15000) as fc:
        pg.get_by_text('Open score', exact=True).first.click()
    fc.value.set_files(xml_path)
    drain_dialogs(pg)
    pg.wait_for_timeout(2500)

    if view == 'printed':
        pg.evaluate(JS_CLICK, 'As printed')
        pg.wait_for_timeout(3000)

    # 判定落档：简谱档才有左侧源码区与 .score-page-wrap 谱面
    page_svgs = pg.evaluate('''() => [...document.querySelectorAll('.score-page-wrap svg')]
      .filter(s => s.outerHTML.length > 800).map(s => s.outerHTML)''')
    src_text = pg.evaluate('''() => {
      const el = document.querySelector('.cm-content');
      return el ? el.innerText : '';
    }''')
    if not page_svgs:
        print(f'  {stem}: 未出简谱页（多声部谱会直接进五线谱/混排视图），跳过')
        return False

    if src_text.strip():
        with open(os.path.join(outdir, f'{stem}.123.txt'), 'w') as f:
            f.write(src_text + '\n')
    for i, svg in enumerate(page_svgs, 1):
        with open(os.path.join(outdir, f'{stem}_p{i}.svg'), 'w') as f:
            f.write(svg)
        cairosvg.svg2pdf(bytestring=svg.encode('utf-8'),
                         write_to=os.path.join(outdir, f'{stem}_p{i}.pdf'))
        cairosvg.svg2png(bytestring=svg.encode('utf-8'),
                         write_to=os.path.join(outdir, f'{stem}_p{i}.png'),
                         background_color='white', output_width=2100)
    print(f'  {stem}: OK，{len(page_svgs)} 页 -> svg/pdf/png + 123 文本')
    return True


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--xml')
    g.add_argument('--batch')
    ap.add_argument('--out', required=True)
    ap.add_argument('--view', choices=['printed', 'expanded'], default='printed')
    args = ap.parse_args()

    if sync_playwright is None or cairosvg is None:
        print('缺依赖：playwright／cairosvg（安装：bash install.sh browser）。本脚本不降级运行。', file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.out, exist_ok=True)
    print('dev server:', ensure_server())

    if args.batch:
        files = sorted(glob.glob(os.path.join(args.batch, '*.musicxml')) +
                       glob.glob(os.path.join(args.batch, '*.xml')))
    else:
        files = [args.xml]
    print(f'待处理 {len(files)} 件')

    ok = 0
    t0 = time.time()
    p = sync_playwright().start()
    b = p.chromium.launch(headless=True)
    try:
        for f in files:
            pg = b.new_page(viewport={'width': 1440, 'height': 900})
            try:
                if convert_file(pg, f, args.out, args.view):
                    ok += 1
            except Exception as e:
                print(f'  {os.path.basename(f)}: FAIL {repr(e)[:140]}')
            finally:
                pg.close()
    finally:
        b.close()
        p.stop()
    print(f'完成 {ok}/{len(files)}，总耗时 {time.time()-t0:.1f}s，输出目录 {args.out}')


if __name__ == '__main__':
    main()
