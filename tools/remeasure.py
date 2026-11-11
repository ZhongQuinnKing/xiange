#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键重测：重建复刻谱 → 自检 → 机器(CREPE)×手工 一致度

用途：每次补读/修正数据后跑一遍，出"当前准确度"数字。
机器侧用 CREPE 稳定音（可设最短时长，去掉滑音伪影），手工侧用精读数据。

用法:
    python3 remeasure.py --pages <页数据.md 或 目录...> --crepe <crepe_notes.csv>

选项:
    --builder <build_facsimile.py>   给了才执行第①步"重建复刻谱"
    -o <out.musicxml>                重建输出（与 --builder 搭配，默认 复刻.musicxml）
    --min-dur <秒>                   CREPE 稳定音最短时长（默认 0.18）
    --t0-min <秒>                    CREPE 起点早于此秒数的音忽略（默认 0.0，不过滤）
    --beats-per-bar <拍>             每小节拍数（默认 4）
    --hand <记号>                    手工侧比较的声部行（默认 RH）

页数据格式：md 内 `## mN` 小节头 + `<hand>: [音名,..]:时值` 行；
CREPE CSV 需含列 t0, dur, beat, midi。
"""
import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path


def machine_by_bar(crepe_path, min_dur=0.18, t0_min=0.0, beats_per_bar=4):
    bars = {}
    with open(crepe_path, newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if float(r['dur']) < min_dur or float(r['t0']) < t0_min:
                continue
            beat = float(r['beat'])
            bar = int(beat // beats_per_bar) + 1
            bars.setdefault(bar, set()).add(int(float(r['midi'])) % 12)
    return bars


def manual_by_bar(page_files, hand="RH"):
    bars = {}
    cur = None
    for p in page_files:
        for line in open(p, encoding='utf-8'):
            line = line.strip()
            m = re.match(r'^##\s*m(\d+)', line)
            if m:
                cur = int(m.group(1)); bars.setdefault(cur, set()); continue
            if cur is None or not line.startswith(hand + ':'):
                continue
            for tok in re.finditer(r'\[([^\]]*)\]', line):
                for nm in tok.group(1).split(','):
                    nm = nm.strip()
                    mm = re.match(r'^([A-Ga-g])([#b-]?)(\d)$', nm)
                    if mm:
                        base = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}[mm.group(1).upper()]
                        acc = {'#': 1, 'b': -1, '-': -1}.get(mm.group(2), 0)
                        bars[cur].add((base + acc) % 12)
    return bars


def collect_pages(paths):
    """展开 --pages 参数：文件直接用；目录展开为其下 *.md（排序）"""
    out = []
    for p in paths:
        pth = Path(p)
        if pth.is_dir():
            out += sorted(pth.glob('*.md'))
        else:
            out.append(pth)
    return out


def main():
    ap = argparse.ArgumentParser(description='重测：重建复刻谱 → 自检 → 机器×手工一致度')
    ap.add_argument('--pages', nargs='+', required=True,
                    help='页数据 md（文件或目录；目录取其下 *.md）')
    ap.add_argument('--crepe', required=True, help='CREPE 音符 CSV（列: t0, dur, beat, midi）')
    ap.add_argument('--builder', help='build_facsimile.py 路径；给了才执行第①步重建')
    ap.add_argument('-o', '--out', default='复刻.musicxml', help='重建输出文件（默认 复刻.musicxml）')
    ap.add_argument('--min-dur', type=float, default=0.18, help='CREPE 稳定音最短时长秒（默认 0.18）')
    ap.add_argument('--t0-min', type=float, default=0.0, help='忽略起点早于此秒数的音（默认 0）')
    ap.add_argument('--beats-per-bar', type=int, default=4, help='每小节拍数（默认 4）')
    ap.add_argument('--hand', default='RH', help='手工侧比较行（默认 RH）')
    args = ap.parse_args()

    page_files = collect_pages(args.pages)
    if not page_files:
        sys.exit('页数据为空：检查 --pages 路径')
    missing = [str(p) for p in page_files if not p.exists()]
    if missing:
        sys.exit('页数据文件不存在：' + '、'.join(missing))
    if not Path(args.crepe).exists():
        sys.exit(f'CREPE CSV 不存在：{args.crepe}')
    if args.builder and not Path(args.builder).exists():
        sys.exit(f'builder 不存在：{args.builder}')

    print("=" * 46)
    if args.builder:
        print("① 重建复刻谱")
        r = subprocess.run([sys.executable, args.builder] +
                           [str(p) for p in page_files] + ["-o", args.out],
                           capture_output=True, text=True)
        for ln in (r.stdout or "").splitlines():
            print("   " + ln)
        if r.returncode != 0:
            print(f"   ⚠ 重建失败（退出码 {r.returncode}），stderr 末几行：")
            for ln in (r.stderr or "").splitlines()[-5:]:
                print("   " + ln)
    else:
        print("① 重建复刻谱（跳过：未给 --builder）")

    print(f"② 机器×手工 旋律层一致度（CREPE 稳定音 vs 手工 {args.hand}）")
    mach = machine_by_bar(args.crepe, args.min_dur, args.t0_min, args.beats_per_bar)
    man = manual_by_bar(page_files, args.hand)
    rows = []
    for b in sorted(set(mach) & set(man)):
        a, m = mach[b], man[b]
        if a and m:
            rows.append((b, len(a & m) / len(a | m)))
    if rows:
        avg = sum(x[1] for x in rows) / len(rows)
        strong = sum(1 for x in rows if x[1] >= 0.5)
        print(f"   可比小节 {len(rows)}｜平均一致度 {avg*100:.1f}%｜≥50% 的小节 {strong}/{len(rows)}")
        print("   最差 5 个: " + ", ".join(f"m{b}({j*100:.0f}%)" for b, j in sorted(rows, key=lambda x: x[1])[:5]))
    else:
        print("   无可比数据（机器侧与手工侧小节无交集，检查输入）")
    print("=" * 46)


if __name__ == "__main__":
    main()
