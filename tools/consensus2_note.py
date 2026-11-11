#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1 音符级（MIDI 音高，含八度）对比与分工式试算
SMT 侧用自写 kern 解析（不借 music21——绕 spine 坑）；octave 按 kern 大小写规则
"""
import re
import sys, glob
import music21

KERN_PC = {'C':0,'D':2,'E':4,'F':5,'G':7,'A':9,'B':11}

def krn_midi_bars(path):
    bars = {}; bar = 1; data = set()
    for ln in open(path, encoding='utf-8', errors='replace').read().split('\n'):
        s = ln.strip()
        if not s or s.startswith('*') or s.startswith('!'): continue
        if s.startswith('='):
            bars[bar] = set(data); bar += 1; data = set()
            continue
        for tok in re.split(r'\s+', ln):
            t = tok.strip('[](){}')
            m = re.match(r'^[0-9.]*([A-Ga-g]+)([#-]*)', t)
            if m:
                letters = m.group(1); n = len(letters)
                pc = KERN_PC[letters[0].upper()]
                octv = 4 + (n - 1) if letters[0].islower() else 3 - (n - 1)
                midi = 12 * (octv + 1) + pc
                for ch in m.group(2):
                    midi += 1 if ch == '#' else -1
                data.add(midi)
    if data: bars[bar] = set(data)
    return bars

def krn_midi_multi(paths):
    seq = []
    for p in paths:
        kb = krn_midi_bars(p)
        seq += [kb[k] for k in sorted(kb)]
    return seq

def bars_midi(path):
    s = music21.converter.parse(path)
    d = {}
    for p in s.parts:
        for m in p.getElementsByClass('Measure'):
            try: num = int(m.number)
            except Exception: continue
            dst = d.setdefault(num, set())
            for n in m.recurse().notes:
                if n.isChord: dst |= {q.midi for q in n.pitches}
                else: dst.add(n.pitch.midi)
    return [d[k] for k in sorted(d)]

def bars_midi_multi(paths):
    seq = []
    for p in paths:
        try: seq += bars_midi(p)
        except Exception as e: print('  skip', p.split('/')[-1], str(e)[:40])
    return seq

def J(a, b): return len(a & b) / len(a | b) if (a | b) else 1.0

T = bars_midi(sys.argv[1])

print('===== B720（1-13 节，MIDI 音高级）=====')
H = bars_midi_multi(sorted(glob.glob('/var/tmp/homr_test/B720_row[1-4].musicxml')))
S = krn_midi_multi(sorted(glob.glob('/var/tmp/b_rows/row_0[1-5]_big.krn')))
Orows = {}
for i, fn in [(1,'row_01'), (3,'row_03'), (4,'row_04')]:
    try: Orows[i] = set().union(*bars_midi(f'/var/tmp/b_rows/{fn}.omr.musicxml'))
    except Exception: pass
spans = {1:(1,4), 3:(11,16), 4:(17,22)}
n = min(13, len(H), len(S))
tot = {'H':0.0, 'S':0.0, 'v02':0.0}
for k in range(n):
    b = k + 1; t = T[k]
    h = H[k] if k < len(H) else set()
    sset = S[k] if k < len(S) else set()
    add = set()
    for ri, (a0, e0) in spans.items():
        if a0 <= b <= e0 and ri in Orows:
            add = (sset & Orows[ri]) - h
    fin = h | add
    tot['H'] += J(h, t); tot['S'] += J(sset, t); tot['v02'] += J(fin, t)
    print(f'  第{b:2d}节  homr {J(h,t):.2f} | SMT {J(sset,t):.2f} | v0.2 {J(fin,t):.2f}（补{len(add)}）')
print(f'平均：homr {tot["H"]/n:.3f} | SMT {tot["S"]/n:.3f} | v0.2 {tot["v02"]/n:.3f}')

print()
print('===== A 版（1-20 节，MIDI 音高级）=====')
HA = bars_midi_multi(sorted(glob.glob('/var/tmp/homr_test/A_row[1-5].musicxml')))
SA = krn_midi_multi(['/var/tmp/smt_rows_merged.krn'])
n2 = min(20, len(HA), len(SA))
th = ts = 0.0
for k in range(n2):
    t = T[k]
    h = HA[k] if k < len(HA) else set()
    sset = SA[k] if k < len(SA) else set()
    th += J(h, t); ts += J(sset, t)
print(f'平均：homr {th/n2:.3f} | SMT {ts/n2:.3f}')

print()
print('===== v0.3 多数票（midi 级：≥2/3 引擎含该音；O 为行级粗证）=====')
tm = ths = 0.0
for k in range(n):
    b = k + 1; t = T[k]
    h = H[k] if k < len(H) else set()
    sset = S[k] if k < len(S) else set()
    o = None
    for ri, (a0, e0) in spans.items():
        if a0 <= b <= e0 and ri in Orows: o = Orows[ri]
    univ = h | sset | (o or set())
    maj = set()
    for note in univ:
        cnt = (note in h) + (note in sset) + (note in (o or set()))
        if cnt >= 2: maj.add(note)
    tm += J(maj, t); ths += J(h & sset, t)
print(f'平均：多数票(≥2/3) {tm/n:.3f} | H∩S 双证 {ths/n:.3f}')
