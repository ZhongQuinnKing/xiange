#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v4 渲染：MusicXML → SVG → PNG（verovio + cairosvg），供自查与对照。"""
import sys

import cairosvg
import verovio


def render(xml, prefix, scale=42):
    tk = verovio.toolkit()
    tk.loadFile(xml)
    tk.setOptions({
        "pageWidth": 2100, "pageHeight": 2970,
        "scale": scale, "adjustPageHeight": True,
        "footer": "none", "header": "none",
    })
    pages = tk.getPageCount()
    out = []
    for i in range(1, pages + 1):
        svg = tk.renderToSVG(i)
        sp = f"{prefix}_p{i}.svg"
        open(sp, "w").write(svg)
        pp = f"{prefix}_p{i}.png"
        cairosvg.svg2png(url=sp, write_to=pp, output_width=1500)
        out.append(pp)
    return pages, out


if __name__ == "__main__":
    xml = sys.argv[1] if len(sys.argv) > 1 else "失眠_钢琴改编_v4.musicxml"
    prefix = sys.argv[2] if len(sys.argv) > 2 else "_v4"
    n, files = render(xml, prefix)
    print(f"共 {n} 页：")
    for f in files:
        print(" ", f)
