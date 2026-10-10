#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vv_render — 交付链主链：MusicXML → verovio → SVG + PNG + PDF（cairosvg）

用法:
  python3 vv_render.py <in.musicxml> <outbase>                     单文件（贴合内容页高）
  python3 vv_render.py --a4 <in.musicxml> <outbase>                单文件 A4 印刷版式
  python3 vv_render.py --a4 --batch <indir> <outdir>               目录批量 A4
  python3 vv_render.py --a4 --fixed-lines <in.musicxml> <outbase>  A4 精确控行（按 MusicXML 内
                                                                   <print new-system> 标记断行）

每个页面同出三件：<outbase>_pN.svg / .png / .pdf。
一页多页自动分页；--a4 走 A4 印刷版式（210×297mm），不加 --a4 贴合内容页高。
依赖: python 包 verovio、cairosvg（批量模式扫描目录下 *.musicxml 与 *.xml）。

--fixed-lines 说明（2026-10-10 版式实验落地）：
  走 breaks='encoded' + redoLayout（实测 breaks 更新必须重排才落实）。
  MusicXML 无 new-system 标记行为同 auto；默认路径（不加此参数）与旧版完全一致。
"""
import sys, os, glob, time, re
import verovio, cairosvg

DPI_A4 = 254  # 2100px * 72/254 = 595.3pt = A4 宽
CJK_TEXT_RE = re.compile(r'<tspan[^>]*>[^<]*[一-鿿]')


def cjk_font_fix(svg):
    """含中文的谱面：把文本字体换成带 CJK 字形的系统字体。

    2026-10-10 实测：verovio 输出的歌词/标题是真文本（font-family="Times, serif"），
    Times 无中文字形，渲染出豆腐块；转换层换 Hiragino 后中文正常。
    触发条件只认"会渲染的文字元素"（元数据里的中文不算），
    不触发时原样返回：既有件输出逐字节不变（png 已实测一致）。
    """
    if CJK_TEXT_RE.search(svg):
        return svg.replace('font-family="Times, serif"', 'font-family="Hiragino Sans GB"')
    return svg

def render(src, outbase, a4, fixed_lines=False):
    tk = verovio.toolkit()
    if not tk.loadFile(src):
        print(f'  LOAD FAIL: {src}')
        return False
    if a4:
        tk.setOptions({
            'pageWidth': 2100, 'pageHeight': 2970, 'scale': 100,
            'adjustPageHeight': False, 'footer': 'none', 'header': 'none',
            'breaks': 'encoded' if fixed_lines else 'auto', 'svgViewBox': True,
            'pageMarginTop': 150, 'pageMarginBottom': 150,
            'pageMarginLeft': 150, 'pageMarginRight': 150,
        })
    else:
        tk.setOptions({
            'pageWidth': 2100, 'pageHeight': 2970, 'scale': 65,
            'adjustPageHeight': True, 'footer': 'none', 'header': 'none',
            'breaks': 'encoded' if fixed_lines else 'auto', 'svgViewBox': True,
        })
    if fixed_lines:
        tk.redoLayout()  # breaks 更新须重排才落实（版式实验实测）
    n = tk.getPageCount()
    for p in range(1, n + 1):
        svg = cjk_font_fix(tk.renderToSVG(p))
        with open(f'{outbase}_p{p}.svg', 'w') as f:
            f.write(svg)
        cairosvg.svg2png(bytestring=svg.encode('utf-8'),
                         write_to=f'{outbase}_p{p}.png', background_color='white',
                         dpi=DPI_A4 if a4 else 96)
        cairosvg.svg2pdf(bytestring=svg.encode('utf-8'),
                         write_to=f'{outbase}_p{p}.pdf',
                         dpi=DPI_A4 if a4 else 96)
    print(f'  OK: {os.path.basename(src)} -> {n} 页')
    return True

def main():
    args = sys.argv[1:]
    a4 = '--a4' in args
    if a4:
        args.remove('--a4')
    batch = '--batch' in args
    if batch:
        args.remove('--batch')
    fixed_lines = '--fixed-lines' in args
    if fixed_lines:
        args.remove('--fixed-lines')
    if batch:
        indir, outdir = args[0], args[1]
        os.makedirs(outdir, exist_ok=True)
        files = sorted(glob.glob(os.path.join(indir, '*.musicxml')) +
                       glob.glob(os.path.join(indir, '*.xml')))
        print(f'批量: {len(files)} 个文件')
        ok = 0
        t0 = time.time()
        for f in files:
            stem = os.path.splitext(os.path.basename(f))[0]
            if render(f, os.path.join(outdir, stem), a4, fixed_lines):
                ok += 1
        print(f'完成 {ok}/{len(files)}，总耗时 {time.time()-t0:.1f}s')
    else:
        t0 = time.time()
        render(args[0], args[1], a4, fixed_lines)
        print(f'耗时 {time.time()-t0:.1f}s')

if __name__ == '__main__':
    main()
