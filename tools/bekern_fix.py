#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 版骨架渲染 v4：自研 spine 归一化（分裂/合并感知）→ 2 列 → music21 → verovio"""
import os

OUT = '/var/tmp/b_rows/render4'


def pick(cols):
    best = ''
    for c in cols:
        t = c.strip()
        if t in ('', '.'):
            continue
        if len(t) > len(best):
            best = t
    return best if best else '.'


def normalize(raw):
    lines = [ln for ln in raw.strip().split('\n')]
    lines = [ln for ln in lines if ln.strip() and not ln.strip().startswith('*-') and not ln.lstrip().startswith('**kern')]
    slots = [1, 2]
    out = []
    for ln in lines:
        cols = ln.split('\t')
        if any(c.strip() in ('*^', '*v') for c in cols):
            new_slots = []
            for j, c in enumerate(cols):
                base = slots[j] if j < len(slots) else (slots[-1] if slots else 1)
                cs = c.strip()
                if cs == '*^':
                    new_slots += [base, base]
                elif cs == '*v':
                    if j > 0 and cols[j-1].strip() == '*v':
                        continue
                    new_slots.append(base)
                else:
                    new_slots.append(base)
            slots = new_slots
            out.append('*\t*')
            continue
        if len(cols) < len(slots):
            cols = cols + ['.'] * (len(slots) - len(cols))
        c1 = pick(cols[j] for j in range(len(slots)) if slots[j] == 1)
        c2 = pick(cols[j] for j in range(len(slots)) if slots[j] == 2)
        out.append(c1 + '\t' + c2)
    return '**kern\t**kern\n' + '\n'.join(out) + '\n*-\t*-'


def main():
    import music21, verovio, cairosvg
    os.makedirs(OUT, exist_ok=True)
    pngs = []
    for i in range(1, 6):
        src = f'/var/tmp/b_rows/row_{i:02d}_big.krn'
        if not os.path.exists(src):
            print(f'row_{i:02d}: 无 krn'); continue
        try:
            raw = open(src).read()
            norm = normalize(raw)
            f1 = f'{OUT}/row_{i:02d}_norm.krn'
            open(f1, 'w').write(norm)
            s = music21.converter.parse(f1)
            n_notes = sum(1 for p in s.parts for n in p.recurse().notes)
            xml = f'{OUT}/row_{i:02d}.musicxml'
            s.write('musicxml', fp=xml)
            tk = verovio.toolkit()
            tk.loadFile(xml)
            tk.setOptions({'pageWidth': 2400, 'pageHeight': 600, 'scale': 50, 'adjustPageHeight': True,
                           'footer': 'none', 'header': 'none', 'breaks': 'none'})
            svg = tk.renderToSVG(1)
            png = f'{OUT}/row_{i:02d}.png'
            cairosvg.svg2png(bytestring=svg.encode('utf-8'), write_to=png,
                             background_color='white', output_width=1400)
            pngs.append(png)
            print(f'row_{i:02d}: OK 声部{len(s.parts)} 音符{n_notes}')
        except Exception as e:
            print(f'row_{i:02d}: FAIL {repr(e)[:120]}')

    if pngs:
        from PIL import Image
        ims = [Image.open(p).convert('RGB') for p in pngs]
        W = 1400
        canvas = Image.new('RGB', (W, sum(im.height for im in ims) + 20 * (len(ims) - 1)), 'white')
        y = 0
        for im in ims:
            canvas.paste(im, (0, y)); y += im.height + 20
        out = '/var/tmp/B_720_skeleton.png'
        canvas.save(out)
        print('竖拼完成:', out, canvas.size)
    return 0


if __name__ == '__main__':
    main()
