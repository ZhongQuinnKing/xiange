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
import sys, os, glob, time
import verovio, cairosvg

DPI_A4 = 254  # 2100px * 72/254 = 595.3pt = A4 宽

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
        svg = tk.renderToSVG(p)
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
