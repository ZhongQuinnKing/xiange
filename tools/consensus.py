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
import os
import re
import sys

from m21_cache import parse_cached

KERN_PC = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
PC_NAME = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
DUR = {'1': 4.0, '2': 2.0, '4': 1.0, '8': 0.5, '16': 0.25, '32': 0.125}


def bars_from_musicxml(path):
    s = parse_cached(path)
    d = {}
    for p in s.parts:
        for mi, m in enumerate(p.getElementsByClass('Measure'), 1):
            # When a measure number is missing (parses as 0), fall back to sequential position (fixed 2026-10-13: missing numbers collapsed all number-keyed grouping)
            num = m.number if isinstance(m.number, int) and m.number > 0 else mi
            pcs = set()
            for n in m.recurse().notes:
                if n.isChord:
                    pcs |= {q.midi % 12 for q in n.pitches}
                else:
                    pcs.add(n.pitch.midi % 12)
            d.setdefault(num, set()).update(pcs)
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
            # Accept both cases: in kern notation lowercase = above middle C, uppercase = below; this tool only uses pitch class, so accept both
            # (fixed 2026-10-13: previously uppercase-only; real SMT lowercase pitches like 8.g were all dropped, leaving side B empty)
            m = re.match(r'^([0-9.]*)([A-Ga-g]+)([#-]?)', t)
            if m and m.group(2):
                acc = 1 if m.group(3) == '#' else (-1 if m.group(3) == '-' else 0)
                out.append((bar, (KERN_PC[m.group(2)[0].upper()] + acc) % 12, DUR.get(m.group(1))))
    return out


def fmt(pcs):
    return ' '.join(PC_NAME[x] for x in sorted(pcs)) if pcs else '（空）'


def seq_events_from_musicxml(path):
    """扁平事件序 [(pc, dur_ql or None)]，按谱面先后。"""
    s = parse_cached(path)
    evs = []
    for p in s.parts:
        for m in p.getElementsByClass('Measure'):
            for n in m.recurse().notes:
                if n.isChord:
                    for q in n.pitches:
                        evs.append((q.midi % 12, float(n.quarterLength)))
                else:
                    evs.append((n.pitch.midi % 12, float(n.quarterLength)))
    return evs


def seq_events_from_bekern(path):
    return [(pc, dur) for (_bar, pc, dur) in notes_from_bekern(path)]


def nw_align(a, b, dur_tol=0.26, gap=-1.0):
    """Needleman-Wunsch 对齐两个事件序。

    打分：同音高类 +2（时值也在容差内再 +0.5）；音高类不同 -1；断层 -1。
    返回 [(i or None, j or None)] 对齐路径。
    """
    n, mlen = len(a), len(b)
    if not n or not mlen:
        return [(i, None) for i in range(n)] + [(None, j) for j in range(mlen)]

    def sim(x, y):
        if x[0] != y[0]:
            return -1.0
        sc = 2.0
        if x[1] is not None and y[1] is not None and abs(x[1] - y[1]) <= dur_tol:
            sc += 0.5
        return sc

    dp = [[0.0] * (mlen + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + gap
    for j in range(1, mlen + 1):
        dp[0][j] = dp[0][j - 1] + gap
    for i in range(1, n + 1):
        ai = a[i - 1]
        for j in range(1, mlen + 1):
            dp[i][j] = max(dp[i - 1][j - 1] + sim(ai, b[j - 1]),
                           dp[i - 1][j] + gap, dp[i][j - 1] + gap)
    path, i, j = [], n, mlen
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + sim(a[i - 1], b[j - 1]):
            path.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + gap:
            path.append((i - 1, None))
            i -= 1
        else:
            path.append((None, j - 1))
            j -= 1
    return list(reversed(path))


def cmd_seq(args):
    """序列对齐共识（可选路径；不改 pc／notes 两法默认）。"""
    A = seq_events_from_musicxml(args.engine_a)
    B = seq_events_from_bekern(args.engine_b)
    path = nw_align(A, B)
    agree = disagree = only_a = only_b = 0
    disp_shown = 0
    print('[序列对齐] 事件对齐结果（前 12 条待裁示例）：')
    for i, j in path:
        if i is not None and j is not None:
            if A[i][0] == B[j][0]:
                agree += 1
            else:
                disagree += 1
                if disp_shown < 12:
                    print(f'  待裁：A[{i}]={PC_NAME[A[i][0]]} vs B[{j}]={PC_NAME[B[j][0]]}')
                    disp_shown += 1
        elif i is not None:
            only_a += 1
        else:
            only_b += 1
    tot = len(path)
    print(f'对齐位 {tot}：同音类 {agree}｜异音类 {disagree}｜仅 A 有 {only_a}｜仅 B 有 {only_b}')

    # Same-piece comparison (pitch-class level, per-measure sets)
    Ab = bars_from_musicxml(args.engine_a)
    Bb = {}
    for (bar, pc, _) in notes_from_bekern(args.engine_b):
        Bb.setdefault(bar, set()).add(pc)
    N = max(max(Ab, default=0), max(Bb, default=0))
    n_cons = n_dis = 0
    for i in range(1, N + 1):
        a_, b_ = Ab.get(i, set()), Bb.get(i, set())
        n_cons += len(a_ & b_)
        n_dis += len((a_ | b_) - (a_ & b_))
    print(f'[现法对照] 小节数 {N}：共识音类 {n_cons}｜待裁音类 {n_dis}'
          f'（待裁占比 {n_dis/max(n_cons+n_dis,1)*100:.0f}%）')
    print('（序列法定位到事件序位，可作局部重试范围；两法并跑对数是 C 组对照实验的口径。）')


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
    if not notes:
        print('骨架音符事件：0 个——B 引擎输出无音符（查 kern 内容或格式），无从比对')
        return
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

    p3 = sub.add_parser('seq', help='序列对齐共识（可选路径，实验用）')
    p3.add_argument('engine_a')
    p3.add_argument('engine_b')
    p3.set_defaults(func=cmd_seq)

    args = ap.parse_args()
    # Missing file: uniform clean rc=2 error (2026-10-13)
    paths = [args.engine_a, args.engine_b] + ([args.truth] if getattr(args, 'truth', None) else [])
    for p in paths:
        if not os.path.exists(p):
            sys.stderr.write(f'读谱失败：{p} 不存在（A 引擎 MusicXML／B 引擎 bekern 路径）\n')
            sys.exit(2)
    args.func(args)


if __name__ == '__main__':
    main()
