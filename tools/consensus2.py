#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""共识 v2 原型（pc 级 v0.1）：质量加权 + 闸门分流
引擎：homr(权重2.0) / SMT(1.5) / oemer(1.0, 行级粗证)
输出：每节"高置信集"（按权重阈值），并与单引擎对比
"""
import re, glob
import music21

KERN_PC = {'C':0,'D':2,'E':4,'F':5,'G':7,'A':9,'B':11}

def krn_bars(path):
    bars = {}; bar = 1; data = []
    for ln in open(path, encoding='utf-8', errors='replace').read().split('\n'):
        s = ln.strip()
        if not s or s.startswith('*') or s.startswith('!'): continue
        if s.startswith('='):
            bars[bar] = set(data); bar += 1; data = []
            continue
        for tok in re.split(r'\s+', ln):
            t = tok.strip('[](){}')
            m = re.match(r'^[0-9.]*([A-Ga-g])([#-]*)', t)
            if m:
                pc = KERN_PC[m.group(1).upper()]
                for ch in m.group(2):
                    pc = (pc + 1) % 12 if ch == '#' else (pc - 1) % 12
                data.append(pc)
    if data: bars[bar] = set(data)
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
        try: s = music21.converter.parse(p)
        except Exception: continue
        measures = {}
        for prt in s.parts:
            for m in prt.getElementsByClass('Measure'):
                try: num = int(m.number)
                except Exception: continue
                pcs = set()
                for n in m.recurse().notes:
                    pcs |= {q.midi % 12 for q in n.pitches} if n.isChord else {n.pitch.midi % 12}
                measures.setdefault(num, set()).update(pcs)
        for k in sorted(measures): seq.append(measures[k])
    return seq

def load_truth():
    s = music21.converter.parse('/Users/user/Desktop/转谱/失眠_LadiesNight/数字源/数字源_Midishow_v4.musicxml')
    c = {}
    for p in s.parts:
        for m in p.getElementsByClass('Measure'):
            try: num = int(m.number)
            except Exception: continue
            pcs = set()
            for n in m.recurse().notes:
                pcs |= {q.midi % 12 for q in n.pitches} if n.isChord else {n.pitch.midi % 12}
            c.setdefault(num, set()).update(pcs)
    return [c.get(i, set()) for i in range(1, 57)]

C = load_truth()
H = homr_bars(sorted(glob.glob('/var/tmp/homr_test/B720_row[1-4].musicxml')))
S = krn_bars('/var/tmp/b_rows/smt_merged.krn')

# SMT 各行小节数 → oemer 行级证据的真值跨度
counts = [4, 6, 6, 6, 0]
spans = []
a = 1
for cn in counts:
    spans.append((a, a + cn - 1)); a += cn
oemer_rows = {1: 'row_01.omr.musicxml', 3: 'row_03.omr.musicxml', 4: 'row_04.omr.musicxml'}
O = {}   # bar -> row-level pcs（无 oemer 的行没有）
for i, (s0, e0) in enumerate(spans, 1):
    if i in oemer_rows:
        pcs = xml_all_pcs(f'/var/tmp/b_rows/{oemer_rows[i]}')
        for b in range(s0, e0 + 1):
            O[b] = pcs

W = {'H': 2.0, 'S': 1.5, 'O': 1.0}
def J(a, b):
    return len(a & b) / len(a | b) if (a | b) else 1.0

n = min(13, len(H), len(S))
print(f'范围 1-{n} 节 | 权重 H{W["H"]}/S{W["S"]}/O{W["O"]}（O 为行级粗证）')
for theta in (0.5, 0.6, 0.7):
    tot_c, tot_r, tot_t = 0.0, 0.0, 0.0
    for k in range(n):
        b = k + 1
        t = C[k]
        members = [('H', H[k], W['H']), ('S', S.get(b, set()), W['S'])]
        if b in O: members.append(('O', O[b], W['O']))
        Wsum = sum(w for _, _, w in members)
        conf = set()
        for pc in range(12):
            sc = sum(w for _, st, w in members if pc in st)
            if sc >= theta * Wsum: conf.add(pc)
        tot_c += J(conf, t)
        tot_r += (len(conf & t) / len(t) if t else 0)
        tot_t += len(conf)
    print(f'θ={theta}: 高置信集平均 J={tot_c/n:.3f} | 平均召回={tot_r/n:.3f} | 平均直通类数={tot_t/n:.1f}')
print()
print('逐节（θ=0.6）:')
for k in range(n):
    b = k + 1; t = C[k]
    members = [('H', H[k], W['H']), ('S', S.get(b, set()), W['S'])]
    if b in O: members.append(('O', O[b], W['O']))
    Wsum = sum(w for _, _, w in members)
    conf = {pc for pc in range(12) if sum(w for _, st, w in members if pc in st) >= 0.6 * Wsum}
    print(f'  第{b:2d}节  homr {J(H[k],t):.2f} | SMT {J(S.get(b,set()),t):.2f} | v2直通 {J(conf,t):.2f}（{len(conf)} 类）')

print()
print('=== v0.2 分工式（骨架=homr 不被票掉；补充=S∩O 双弱共识新增；不删只记） ===')
tot02 = 0.0; totr02 = 0.0
for k in range(n):
    b = k + 1; t = C[k]
    base = H[k]
    add = set()
    if b in O:
        add = (S.get(b, set()) & O[b]) - base
    final = base | add
    tot02 += J(final, t); totr02 += (len(final & t) / len(t) if t else 0)
    print(f'  第{b:2d}节 骨架J {J(base,t):.2f} → v0.2 J {J(final,t):.2f}（补 {len(add)} 类）')
print(f'v0.2 平均 J = {tot02/n:.3f} | 平均召回 = {totr02/n:.3f}')
