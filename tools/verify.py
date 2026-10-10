#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数字源验证三件套（技能包 tools）

依赖: pip install music21 numpy

用法:
  python verify.py metadata <文件> [--notes N] [--bpm B] [--dur 秒]
      元数据核对：音符数/BPM/时长，与标称对比
  python verify.py dist <文件A> <文件B>
      分布对拍：两文件音高类直方图余弦（0.95 以上约等于同一首）
  python verify.py align <数字源文件> <对照转录文件> [--bars N] [--bpm B]
      逐小节对齐：音高类 Jaccard 加偏移扫描，找最优对齐

坑提醒：music21 的 offset 单位是"拍"不是秒；跨文件对比按各文件自身 tempo 换算。
无 tempo 标记的文件按 120 BPM（Basic Pitch 输出即如此）。align 的对照侧默认按
曲速 68 BPM、4/4 折算小节，曲子速度不同请改 --bpm。
"""
import argparse
from collections import Counter

import numpy as np
from music21 import converter

PC = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def _load(path):
    return converter.parse(path)


def _file_bpm(score):
    mm = list(score.recurse().getElementsByClass('MetronomeMark'))
    return float(mm[0].number) if mm else 120.0


def cmd_metadata(args):
    s = _load(args.file)
    notes = list(s.recurse().notes)
    n_events = len(notes)
    n_notes = sum(len(e.pitches) if e.isChord else 1 for e in notes)
    bpm = _file_bpm(s)
    secs = s.highestTime / bpm * 60
    print(f'音符元素数(和弦算1): {n_events}')
    print(f'展开音数(和弦展开): {n_notes}')
    print(f'文件 tempo: {bpm}')
    print(f'时长(按文件 tempo): {secs:.0f} 秒 = {int(secs // 60)}:{int(secs % 60):02d}')
    if args.notes:
        print(f'标称音符数 {args.notes} -> 差 {n_notes - args.notes:+d}')
    if args.bpm:
        print(f'标称 BPM {args.bpm}')
    if args.dur:
        print(f'标称时长 {args.dur} 秒 -> 差 {secs - args.dur:+.0f} 秒')


def _pc_hist(score):
    c = Counter()
    for n in score.recurse().notes:
        if n.isChord:
            for p in n.pitches:
                c[p.midi % 12] += 1
        else:
            c[n.pitch.midi % 12] += 1
    total = sum(c.values()) or 1
    return np.array([c[i] / total for i in range(12)])


def cmd_dist(args):
    ha, hb = _pc_hist(_load(args.fileA)), _pc_hist(_load(args.fileB))
    cos = float(np.dot(ha, hb) / (np.linalg.norm(ha) * np.linalg.norm(hb)))
    print('音高类   ', ' '.join(f'{n:>5}' for n in PC))
    print('文件A    ', ' '.join(f'{x:5.2f}' for x in ha))
    print('文件B    ', ' '.join(f'{x:5.2f}' for x in hb))
    tag = '  （0.95 以上约等于同一首）' if cos >= 0.95 else ''
    print(f'余弦相似度: {cos:.3f}{tag}')


def _bars_by_measure(score):
    out = {}
    for p in score.parts:
        for m in p.getElementsByClass('Measure'):
            pcs = set()
            for n in m.recurse().notes:
                if n.isChord:
                    pcs |= {q.midi % 12 for q in n.pitches}
                else:
                    pcs.add(n.pitch.midi % 12)
            out.setdefault(m.number, set()).update(pcs)
    return out


def _bars_by_seconds(score, bpm):
    fb = _file_bpm(score)
    out = {}
    for n in score.recurse().notes:
        sec = float(n.getOffsetInHierarchy(score)) * 60.0 / fb
        bar = int(sec * bpm / 60.0 // 4) + 1
        pcs = {p.midi % 12 for p in n.pitches} if n.isChord else {n.pitch.midi % 12}
        out.setdefault(bar, set()).update(pcs)
    return out


def cmd_align(args):
    ba = _bars_by_measure(_load(args.digital))
    bb = _bars_by_seconds(_load(args.other), args.bpm)
    N = args.bars

    def score_off(off):
        vals = []
        for i in range(1, N + 1):
            x, y = ba.get(i, set()), bb.get(i + off, set())
            if x | y:
                vals.append(len(x & y) / len(x | y))
        return sum(vals) / len(vals) if vals else 0.0

    scan = [(o, score_off(o)) for o in range(-8, 9)]
    best_off, best = max(scan, key=lambda t: t[1])
    print(f'数字源小节数 {max(ba) if ba else 0} | 对照折算小节数 {max(bb) if bb else 0}')
    for o, v in scan:
        print(f'  offset={o:+d}: {v:.3f}' + ('  <<最优' if o == best_off else ''))
    good = 0
    for i in range(1, N + 1):
        x, y = ba.get(i, set()), bb.get(i + best_off, set())
        if x | y and len(x & y) / len(x | y) >= 0.6:
            good += 1
    print(f'>> 最优 offset={best_off:+d}，平均一致度={best:.3f}；一致度不低于 0.6 的小节: {good}/{N}')
    print('（Jaccard 受对照源自身精度封顶，是下界指标）')


def main():
    ap = argparse.ArgumentParser(description='数字源验证三件套')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p1 = sub.add_parser('metadata', help='元数据核对')
    p1.add_argument('file')
    p1.add_argument('--notes', type=int)
    p1.add_argument('--bpm', type=float)
    p1.add_argument('--dur', type=float)
    p1.set_defaults(func=cmd_metadata)

    p2 = sub.add_parser('dist', help='分布对拍')
    p2.add_argument('fileA')
    p2.add_argument('fileB')
    p2.set_defaults(func=cmd_dist)

    p3 = sub.add_parser('align', help='逐小节对齐＋偏移扫描')
    p3.add_argument('digital')
    p3.add_argument('other')
    p3.add_argument('--bars', type=int, default=56)
    p3.add_argument('--bpm', type=float, default=68.0)
    p3.set_defaults(func=cmd_align)

    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
