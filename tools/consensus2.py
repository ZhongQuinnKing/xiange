#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""共识 v2 合并试算：多引擎小节级音高类集合的加权合并与门限输出。

权重、门限列表、真值、各引擎产物均由参数给定（必填；缺省即报错）。
输出：每节高置信集（按权重门限），并与单引擎对比。

用法示例:
    python3 consensus2.py --truth 真值.musicxml --homr 甲.musicxml 乙.musicxml \\
        --smt 汇总.krn --w-h 2.0 --w-s 1.5 --w-o 1.0 --thetas 0.5,0.6,0.7 \\
        [--oemer-row 1=行1.musicxml --oemer-span 1=1-4] [--limit N]
"""
import argparse
import re
import sys

import music21

KERN_PC = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}


def krn_bars(path):
    bars = {}
    bar = 1
    data = []
    for ln in open(path, encoding='utf-8', errors='replace').read().split('\n'):
        s = ln.strip()
        if not s or s.startswith('*') or s.startswith('!'):
            continue
        if s.startswith('='):
            bars[bar] = set(data)
            bar += 1
            data = []
            continue
        for tok in re.split(r'\s+', ln):
            t = tok.strip('[](){}')
            m = re.match(r'^[0-9.]*([A-Ga-g])([#-]*)', t)
            if m:
                pc = KERN_PC[m.group(1).upper()]
                for ch in m.group(2):
                    pc = (pc + 1) % 12 if ch == '#' else (pc - 1) % 12
                data.append(pc)
    if data:
        bars[bar] = set(data)
    return bars


def xml_all_pcs(path):
    s = music21.converter.parse(path)
    out = set()
    for p in s.parts:
        for n in p.recurse().notes:
            out |= {q.midi % 12 for q in n.pitches} if n.isChord else {n.pitch.midi % 12}
    return out


def homr_bars(paths):
    seq = []
    for p in paths:
        try:
            s = music21.converter.parse(p)
        except Exception:
            continue
        measures = {}
        for prt in s.parts:
            for m in prt.getElementsByClass('Measure'):
                try:
                    num = int(m.number)
                except Exception:
                    continue
                pcs = set()
                for n in m.recurse().notes:
                    pcs |= {q.midi % 12 for q in n.pitches} if n.isChord else {n.pitch.midi % 12}
                measures.setdefault(num, set()).update(pcs)
        for k in sorted(measures):
            seq.append(measures[k])
    return seq


def load_truth(path):
    s = music21.converter.parse(path)
    c = {}
    for p in s.parts:
        for m in p.getElementsByClass('Measure'):
            try:
                num = int(m.number)
            except Exception:
                continue
            pcs = set()
            for n in m.recurse().notes:
                pcs |= {q.midi % 12 for q in n.pitches} if n.isChord else {n.pitch.midi % 12}
            c.setdefault(num, set()).update(pcs)
    top = max(c) if c else 0
    return [c.get(i, set()) for i in range(1, top + 1)]


def main():
    ap = argparse.ArgumentParser(description='共识 v2 合并试算（参数化；缺省即报错）')
    ap.add_argument('--truth', required=True, help='真值 MusicXML（逐小节音高类集合）')
    ap.add_argument('--homr', nargs='+', required=True, help='homr 产物（按序拼节）')
    ap.add_argument('--smt', required=True, help='SMT 汇总 krn')
    ap.add_argument('--w-h', type=float, required=True, help='H 引擎权重')
    ap.add_argument('--w-s', type=float, required=True, help='S 引擎权重')
    ap.add_argument('--w-o', type=float, required=True, help='O 引擎权重')
    ap.add_argument('--thetas', required=True, help='门限列表，逗号分隔')
    ap.add_argument('--oemer-row', nargs='*', default=[], metavar='行=文件',
                    help='oemer 行级产物（可多组）')
    ap.add_argument('--oemer-span', nargs='*', default=[], metavar='行=起-止',
                    help='各行对应真值小节跨度（可多组）')
    ap.add_argument('--limit', type=int, default=None, help='只算前 N 节（缺省全算）')
    args = ap.parse_args()

    W = {'H': args.w_h, 'S': args.w_s, 'O': args.w_o}
    thetas = [float(x) for x in args.thetas.split(',') if x.strip()]

    C = load_truth(args.truth)
    H = homr_bars(args.homr)
    S = krn_bars(args.smt)

    spans = {}
    for kv in args.oemer_span:
        k, v = kv.split('=')
        a, b = v.split('-')
        spans[int(k)] = (int(a), int(b))
    O = {}
    for kv in args.oemer_row:
        k, f = kv.split('=')
        if int(k) not in spans:
            sys.exit(f'oemer 行 {k} 缺跨度（须配 --oemer-span {k}=起-止）')
        pcs = xml_all_pcs(f)
        s0, e0 = spans[int(k)]
        for b in range(s0, e0 + 1):
            O[b] = pcs

    def J(a, b):
        return len(a & b) / len(a | b) if (a | b) else 1.0

    n = min(len(H), len(S), len(C))
    if args.limit:
        n = min(n, args.limit)
    print(f'范围 1-{n} 节 | 权重 H{W["H"]}/S{W["S"]}/O{W["O"]}（O 为行级粗证）')
    for theta in thetas:
        tot_c, tot_r, tot_t = 0.0, 0.0, 0.0
        for k in range(n):
            b = k + 1
            t = C[k]
            members = [('H', H[k], W['H']), ('S', S.get(b, set()), W['S'])]
            if b in O:
                members.append(('O', O[b], W['O']))
            Wsum = sum(w for _, _, w in members)
            conf = set()
            for pc in range(12):
                sc = sum(w for _, st, w in members if pc in st)
                if sc >= theta * Wsum:
                    conf.add(pc)
            tot_c += J(conf, t)
            tot_r += (len(conf & t) / len(t) if t else 0)
            tot_t += len(conf)
        print(f'θ={theta}: 高置信集平均 J={tot_c/n:.3f} | 平均召回={tot_r/n:.3f} | 平均直通类数={tot_t/n:.1f}')
    print()
    th_mid = thetas[0]
    print(f'逐节（θ={th_mid}）:')
    for k in range(n):
        b = k + 1
        t = C[k]
        members = [('H', H[k], W['H']), ('S', S.get(b, set()), W['S'])]
        if b in O:
            members.append(('O', O[b], W['O']))
        Wsum = sum(w for _, _, w in members)
        conf = {pc for pc in range(12)
                if sum(w for _, st, w in members if pc in st) >= th_mid * Wsum}
        print(f'  第{b:2d}节  homr {J(H[k], t):.2f} | SMT {J(S.get(b, set()), t):.2f} | v2直通 {J(conf, t):.2f}（{len(conf)} 类）')

    print()
    print('v0.2 组合式（以 H 为骨架，S∩O 交集补充）:')
    tot02 = 0.0
    totr02 = 0.0
    for k in range(n):
        b = k + 1
        t = C[k]
        base = H[k]
        add = set()
        if b in O:
            add = (S.get(b, set()) & O[b]) - base
        final = base | add
        tot02 += J(final, t)
        totr02 += (len(final & t) / len(t) if t else 0)
        print(f'  第{b:2d}节 骨架J {J(base, t):.2f} → 组合J {J(final, t):.2f}（补 {len(add)} 类）')
    print(f'组合式平均 J = {tot02/n:.3f} | 平均召回 = {totr02/n:.3f}')


if __name__ == '__main__':
    main()
