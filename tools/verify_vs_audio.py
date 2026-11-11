#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""机器(音频) vs 手工(谱面精读) 逐小节一致性测量

原理：原曲录音为 G 调，陈威全谱为 C 调 → 机器音高 +5 半音后与谱面同调，
再比每小节的**音高类集合**（pitch-class set），算 Jaccard 相似度。
注意：机器轨含伴奏残留，谱面数据含双手——此指标是**下界估计**，非绝对准确率。

用法:
    python3 verify_vs_audio.py [--machine MID] [--manual MD [MD ...]] [--transpose N]
退出码: 0=出数；2=输入缺（机器轨／手工数据不存在）
"""
import argparse
import os
import re
import sys

from music21 import converter

PC = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def load_machine(mid_path, transpose=5):
    s = converter.parse(mid_path)
    ev = []
    for n in s.recurse().notes:
        if n.isNote:
            ev.append((float(n.getOffsetInHierarchy(s)), n.pitch.midi + transpose))
    ev.sort()
    scale = 211.0 / ev[-1][0] if ev else 0.5
    qps = 68 / 60.0
    bars = {}
    for off, midi in ev:
        sec = off * scale
        beat = sec * qps
        bar = int(beat // 4) + 1
        bars.setdefault(bar, set()).add(int(midi) % 12)
    return bars


def load_manual(md_paths):
    bars = {}
    cur = None
    for p in md_paths:
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            m = re.match(r"^##\s*m(\d+)", line)
            if m:
                cur = int(m.group(1)); bars.setdefault(cur, set()); continue
            if cur is None:
                continue
            for hand in ("RH", "LH"):
                if line.startswith(hand + ":"):
                    for tok in re.finditer(r"\[([^\]]*)\]", line):
                        for nm in tok.group(1).split(","):
                            nm = nm.strip()
                            if not nm or "?" in nm or nm == "R":
                                continue
                            mm = re.match(r"^([A-Ga-g])([#b-]?)(\d)$", nm)
                            if mm:
                                step = mm.group(1).upper()
                                acc = {'#': 1, 'b': -1, '-': -1}.get(mm.group(2), 0)
                                base = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}[step]
                                bars[cur].add((base + acc) % 12)
    return bars


def main():
    ap = argparse.ArgumentParser(description='机器(音频) vs 手工(谱面精读) 逐小节音高类一致度')
    ap.add_argument('--machine', default='/var/tmp/shimian_audio/bp_out/vocals_basic_pitch.mid',
                    help='机器转录 MIDI（默认＝原工作流路径）')
    ap.add_argument('--manual', nargs='+',
                    default=['/var/tmp/jp/pages/page1_data.md',
                             '/var/tmp/jp/pages/page2_data.md',
                             '/var/tmp/jp/pages/page3_data.md'],
                    help='手工精读页数据 md（可多份；默认＝原工作流三页）')
    ap.add_argument('--transpose', type=int, default=5,
                    help='机器轨移调半音（默认 5；原曲 G→谱面 C）')
    args = ap.parse_args()

    if not os.path.exists(args.machine):
        sys.stderr.write(f'机器轨不存在：{args.machine}（--machine 可指定）\n')
        sys.exit(2)
    miss = [p for p in args.manual if not os.path.exists(p)]
    if miss:
        sys.stderr.write('手工数据不存在：%s（--manual 可指定）\n' % '、'.join(miss))
        sys.exit(2)

    machine = load_machine(args.machine, transpose=args.transpose)
    manual = load_manual(args.manual)
    common = sorted(set(machine) & set(manual))
    rows = []
    for b in common:
        a, m = machine[b], manual[b]
        if not a or not m:
            continue
        j = len(a & m) / len(a | m)
        rows.append((b, j, sorted(PC[x] for x in a), sorted(PC[x] for x in m)))
    if not rows:
        print("无可比小节")
        return
    avg = sum(r[1] for r in rows) / len(rows)
    print(f"可比较小节：{len(rows)}")
    print(f"平均音高类一致度（Jaccard）：{avg*100:.1f}%  ← 下界估计")
    good = [r for r in rows if r[1] >= 0.5]
    print(f"一致度≥50% 的小节：{len(good)}/{len(rows)} = {len(good)/len(rows)*100:.0f}%")
    print("\n最低的 8 个（重点核查对象）：")
    for b, j, a, m in sorted(rows, key=lambda r: r[1])[:8]:
        print(f"  m{b:2d} {j*100:4.0f}%  机器:{'/'.join(a):22s} 手工:{'/'.join(m)}")


if __name__ == "__main__":
    main()
