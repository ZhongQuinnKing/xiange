#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具_定调.py —— 歌者音域 → 建议调（"迅速移调"工作流前半）。

用法:
  python3 工具_定调.py <谱.musicxml> <最低音> <最高音>
  音域写法：A3 E5（科学音高记号，C4 = 中央 C；可带 #/b，如 F#4、Bb3）
机制：量谱面旋律音域（钢琴大谱表取第 1 谱表旋律行；无谱表信息取全谱并注明）；
     对每个候选调算装得下的最小位移（含 ±12 换八度档），按位移从小到大报出，
     并给出可直接复制的 工具_移调.py 命令。
边界：曲跨 > 歌者跨时任何移调都装不下，如实报，不硬凑。
场景：歌者音域不同 → 先定移去哪，再一键移（配 工具_移调.py 成完整工作流）。
"""
import os
import re
import sys

BASE = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
NAMES_S = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
NAMES_F = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']
FIFTHS = {'C': 0, 'G': 1, 'D': 2, 'A': 3, 'E': 4, 'B': 5, 'F#': 6,
          'F': -1, 'Bb': -2, 'Eb': -3, 'Ab': -4, 'Db': -5, 'Gb': -6}
PITCH_RE = re.compile(
    r'<pitch><step>([A-G])</step>(?:<alter>(-?\d)</alter>)?<octave>(\d)</octave></pitch>')


def midi_of(s, a, o):
    return BASE[s] + a + (o + 1) * 12


def parse_note(txt):
    m = re.fullmatch(r'([A-G])([#b]?)(\d)', txt.strip())
    if not m:
        return None
    a = 1 if m.group(2) == '#' else (-1 if m.group(2) == 'b' else 0)
    return midi_of(m.group(1), a, int(m.group(3)))


def fmt(p, flat):
    names = NAMES_F if flat else NAMES_S
    return f'{names[p % 12]}{p // 12 - 1}'


def piece_range(txt):
    """旋律音域：有旋律谱表信息时取第 1 谱表；否则取全谱。返回 (lo, hi, 口径)。"""
    pits_all, pits_mel = [], []
    for note in re.findall(r'<note>.*?</note>', txt, re.S):
        pm = PITCH_RE.search(note)
        if not pm:
            continue
        p = midi_of(pm.group(1), int(pm.group(2) or 0), int(pm.group(3)))
        pits_all.append(p)
        sm = re.search(r'<staff>(\d+)</staff>', note)
        if sm and sm.group(1) == '1':
            pits_mel.append(p)
    if pits_mel:
        return min(pits_mel), max(pits_mel), '第 1 谱表（旋律行）'
    return min(pits_all), max(pits_all), '全谱（无谱表信息，含伴奏，近似）'


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    src, lo_s, hi_s = sys.argv[1], sys.argv[2], sys.argv[3]
    s_lo, s_hi = parse_note(lo_s), parse_note(hi_s)
    if s_lo is None or s_hi is None or s_lo >= s_hi:
        print(f'歌者音域写法不对：{lo_s} {hi_s}（例：A3 E5）')
        sys.exit(1)
    txt = open(src, encoding='utf-8').read()
    m = re.search(r'<fifths>(-?\d+)</fifths>', txt)
    if not m:
        print('源文件未找到 <fifths>，无法自动判源调')
        sys.exit(1)
    src_f = int(m.group(1))
    lo, hi, how = piece_range(txt)
    span_p, span_s = hi - lo, s_hi - s_lo
    print(f'谱面：{os.path.basename(src)}（源调 fifths={src_f}）')
    print(f'  旋律音域：{fmt(lo, src_f < 0)}–{fmt(hi, src_f < 0)}'
          f'（MIDI {lo}–{hi}，跨 {span_p} 半音，按{how}）')
    print(f'歌者音域：{lo_s}–{hi_s}（MIDI {s_lo}–{s_hi}，跨 {span_s} 半音）')
    if span_p > span_s:
        print(f'× 曲跨 {span_p} > 歌者跨 {span_s}：任何移调都装不下。'
              f'需把旋律跨度压到 {span_s} 半音以内（现 {span_p}，须消 {span_p - span_s}），或换歌者。')
        return
    best = {}
    for tgt, tgt_f in FIFTHS.items():
        m12 = ((tgt_f - src_f) * 7) % 12
        cand = [n for n in (m12 + 12 * k for k in (-2, -1, 0, 1, 2))
                if s_lo <= lo + n and hi + n <= s_hi]
        if cand:
            best[tgt] = (min(cand, key=abs), tgt_f)
    if not best:
        print('× 候选调逐一试过，都装不下：把歌者音域再核一遍，或换歌者。')
        return
    rows = sorted(best.items(), key=lambda kv: (abs(kv[1][0]), kv[1][0]))
    print('—— 可用调（每调取装得下的最小位移；同声异名调并列）——')
    for tgt, (n, tgt_f) in rows[:8]:
        d = '原位' if n == 0 else f'{"上" if n > 0 else "下"} {abs(n)} 半音'
        print(f'  {tgt} 调：{d}｜移后音域 {fmt(lo + n, tgt_f < 0)}–{fmt(hi + n, tgt_f < 0)}'
              f'｜余量 低 {lo + n - s_lo}／高 {s_hi - (hi + n)}')
    if len(rows) > 8:
        print(f'  （另 {len(rows) - 8} 个调也装得下，略）')
    tgt_rec, (n_rec, _f) = rows[0]
    if n_rec == 0:
        print('推荐：原位即可，不用移。')
    else:
        print(f'推荐命令：python3 工具_移调.py "{src}" {tgt_rec}{n_rec:+d}')


if __name__ == '__main__':
    main()
