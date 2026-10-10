#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多引擎共识融合（技能包 tools）

两个 OMR 引擎读同一份谱，交叉出"高置信部分"与"待裁决清单"。
- **pc 模式**（音高类级）：逐小节取共识音高类；分歧列待裁。
- **notes 模式**（音符级）：以 B 引擎（bekern，带时值结构）为骨架，
  给每个音符配 A 引擎的同小节音高佐证（✓ 有佐证 / ? 待裁）。

依赖: pip install music21
用法:
  python consensus.py pc    <A.musicxml> <B.krn> [--truth 真值.musicxml] [--bars N]
  python consensus.py notes <A.musicxml> <B.krn>

A 引擎：MusicXML 类输出（如 oemer）
B 引擎：bekern 文本类输出（如 SMT 的 .krn，多行文件请先按序合并）
--truth（仅 pc 模式）：可选真值，用于评估（共识正确率与单引擎对比）
"""
import argparse
import re

import music21

KERN_PC = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
PC_NAME = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
DUR = {'1': 4.0, '2': 2.0, '4': 1.0, '8': 0.5, '16': 0.25, '32': 0.125}


def bars_from_musicxml(path):
    s = music21.converter.parse(path)
    d = {}
    for p in s.parts:
        for m in p.getElementsByClass('Measure'):
            pcs = set()
            for n in m.recurse().notes:
                if n.isChord:
                    pcs |= {q.midi % 12 for q in n.pitches}
                else:
                    pcs.add(n.pitch.midi % 12)
            d.setdefault(m.number, set()).update(pcs)
    return d


def notes_from_bekern(path):
    """返回 [(bar, pc, dur or None)]；bar 从 1 起。"""
    out, bar = [], 1
    for ln in open(path).read().split('\n'):
        s = ln.strip()
        if not s or s.startswith('*'):
            continue
        if s.startswith('='):
            bar += 1
            continue
        for tok in re.split(r'\s+', ln):
            if tok == '.':
                continue
            t = tok.strip('[](){}')
            m = re.match(r'^([0-9.]*)([A-G]+)([#-]?)', t)
            if m and m.group(2):
                acc = 1 if m.group(3) == '#' else (-1 if m.group(3) == '-' else 0)
                out.append((bar, (KERN_PC[m.group(2)[0]] + acc) % 12, DUR.get(m.group(1))))
    return out


def fmt(pcs):
    return ' '.join(PC_NAME[x] for x in sorted(pcs)) if pcs else '（空）'


def cmd_pc(args):
    A, B = bars_from_musicxml(args.engine_a), {}
    for i, (bar, pc, _) in enumerate(notes_from_bekern(args.engine_b), 1):
        B.setdefault(bar, set()).add(pc)
    T = bars_from_musicxml(args.truth) if args.truth else None
    N = args.bars or max(max(A, default=0), max(B, default=0))
    n_cons = n_disp = ok = tot = 0
    for i in range(1, N + 1):
        a, b = A.get(i, set()), B.get(i, set())
        cons, disp = a & b, (a | b) - (a & b)
        n_cons, n_disp = n_cons + len(cons), n_disp + len(disp)
        line = f'm{i}: 共识 [{fmt(cons)}]'
        if disp:
            line += f' | 待裁 [{fmt(disp)}]'
        if T is not None and cons:
            t = T.get(i, set())
            c = len(cons & t) / len(cons)
            ok += len(cons & t)
            tot += len(cons)
            line += f' | 共识正确率 {c:.2f}'
        print(line)
    print()
    print(f'总计：共识音类 {n_cons}，待裁音类 {n_disp}（待裁占比 {n_disp/(n_cons+n_disp)*100:.0f}%）')
    if T is not None and tot:
        print(f'共识部分加权正确率：{ok/tot:.3f}')


def cmd_notes(args):
    A = bars_from_musicxml(args.engine_a)
    notes = notes_from_bekern(args.engine_b)
    sup = 0
    miss = {}
    for bar, pc, dur in notes:
        if pc in A.get(bar, set()):
            sup += 1
        else:
            miss.setdefault(bar, set()).add(pc)
    print(f'骨架音符事件：{len(notes)} 个')
    print(f'有 A 引擎佐证：{sup} 个（{sup/len(notes)*100:.0f}%）；无佐证待裁：{len(notes)-sup} 个')
    if miss:
        print('待裁清单（小节：音高类）:')
        for b in sorted(miss):
            print(f'  m{b}: {fmt(miss[b])}')
    print('（佐证为"同小节同音高类"级；按拍位、八度、时值的严格化是下一迭代。）')


def main():
    ap = argparse.ArgumentParser(description='多引擎共识融合')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p1 = sub.add_parser('pc', help='音高类级共识')
    p1.add_argument('engine_a')
    p1.add_argument('engine_b')
    p1.add_argument('--truth', default=None)
    p1.add_argument('--bars', type=int, default=None)
    p1.set_defaults(func=cmd_pc)

    p2 = sub.add_parser('notes', help='音符级骨架＋佐证')
    p2.add_argument('engine_a')
    p2.add_argument('engine_b')
    p2.set_defaults(func=cmd_notes)

    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
