#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键重测：重建复刻谱 → 自检 → 机器(CREPE)×手工 一致度

用途：每次补读/修正数据后跑一遍，出"当前准确度"数字。
机器侧用 CREPE 稳定音（≥0.18s，去掉滑音伪影），手工侧用分身精读数据。
"""
import csv
import re
import subprocess
import sys

PC = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
PAGES = ["/var/tmp/jp/pages/page1_data.md",
         "/var/tmp/jp/pages/page2_data.md",
         "/var/tmp/jp/pages/page3_data.md"]
CREPE = "/var/tmp/shimian_audio/crepe_notes.csv"


def machine_by_bar(min_dur=0.18):
    bars = {}
    for r in csv.DictReader(open(CREPE)):
        if float(r['dur']) < min_dur or float(r['t0']) < 13.9:
            continue
        beat = float(r['beat'])
        bar = int(beat // 4) + 1
        bars.setdefault(bar, set()).add(int(float(r['midi'])) % 12)
    return bars


def manual_by_bar(hand="RH"):
    bars = {}
    cur = None
    for p in PAGES:
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


def main():
    print("=" * 46)
    print("① 重建复刻谱")
    r = subprocess.run([sys.executable, "build_facsimile.py"] + PAGES +
                       ["-o", "复刻_陈威全版.musicxml"],
                       capture_output=True, text=True)
    for ln in (r.stdout or "").splitlines():
        print("   " + ln)

    print("② 机器×手工 旋律层一致度（CREPE 稳定音 vs 手工 RH）")
    mach = machine_by_bar()
    man = manual_by_bar("RH")
    rows = []
    for b in sorted(set(mach) & set(man)):
        a, m = mach[b], man[b]
        if a and m:
            rows.append((b, len(a & m) / len(a | m)))
    if rows:
        avg = sum(x[1] for x in rows) / len(rows)
        strong = sum(1 for x in rows if x[1] >= 0.5)
        print(f"   可比小节 {len(rows)}｜平均一致度 {avg*100:.1f}%｜≥50% 的小节 {strong}/{len(rows)}")
        print(f"   最差 5 个: " + ", ".join(f"m{b}({j*100:.0f}%)" for b, j in sorted(rows, key=lambda x: x[1])[:5]))
    else:
        print("   无可比数据")
    print("=" * 46)


if __name__ == "__main__":
    main()
