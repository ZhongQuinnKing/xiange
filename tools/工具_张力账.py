#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具_张力账.py —— MusicXML → 分段三量表（张力账）。

口径（可复核，全部从乐谱直接数出）：
  1. 织体密度 = 段内发声音符总数 / 段内拍数（含和弦音，一个音算一次发音）
  2. 音区重心 = 段内 RH 平均 MIDI / LH 平均 MIDI（音名换算 C4=60）
  3. 和声张力 = 段内"三音及以上同时发音"的发音点占比（柱式和弦/密集织体代理量）
     ＋ 离调音数（相对给定调内音集，调集外记数；无离调=0 不打印）
分段默认 [1-4, 5-8, 9-12, 13-16]，段题可命令行给。
用法:
  python3 工具_张力账.py <file.musicxml> [调内音集，如 C-D-Eb-F-G-Ab-Bb-B] [分段，如 1-8,9-16]
  调内音集写法 = 音名0/-/+（0 本位、- 降、+ 升），逗号分隔；留空用默认 C 小调＋导音集。
多声部形态：首 part 为主声部（人声/旋律）记 RH 侧，其余 part 全归伴奏侧
（歌与单 part 双 staff 两种形态通吃）。
"""
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

STEP_SEMI = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
DEFAULT_PC = {'C0', 'D0', 'E-', 'F0', 'G0', 'A-', 'B-', 'B0'}  # default set: C minor with leading tone
SEGS = [(1, 4), (5, 8), (9, 12), (13, 16)]


def main(path, pc_set, segs=None):
    global SEGS
    if segs:
        SEGS = segs
    root = ET.parse(path).getroot()
    part = root.find('part')
    # beats per measure from the file's own time signature (default 2/4 only if absent)
    time_el = root.find('.//time')
    if time_el is not None and time_el.find('beats') is not None:
        per_measure = int(time_el.find('beats').text) * 4 / int(time_el.find('beat-type').text)
    else:
        per_measure = 2
    # measure -> (staff, [ (onset, [midis], is_chord_group) ])
    seg_stat = {s: {'notes': 0, 'beats': 0, 'rh': [], 'lh': [],
                    'onsets': 0, 'onsets_ge3': 0, 'out_of_key': 0} for s in SEGS}

    def seg_of(mnum):
        for s in SEGS:
            if s[0] <= mnum <= s[1]:
                return s
        return None

    def scan(part_el, all_to_lh):
        for meas in part_el.findall('measure'):
            mnum = int(meas.get('number'))
            s = seg_of(mnum)
            if s is None:
                continue
            st = seg_stat[s]
            # per-staff cursors (onset counted in divisions from measure start)
            cur = {'1': 0, '2': 0}    # next non-chord note advances this
            last = {'1': 0, '2': 0}   # most recent onset (<chord/> notes attach here)
            onset_map = defaultdict(list)   # (staff, onset) -> [midi]
            for note in meas.findall('note'):
                staff_el = note.find('staff')
                staff = staff_el.text if staff_el is not None else '1'
                dur = int(note.find('duration').text)
                pitch = note.find('pitch')
                alter_el = pitch.find('alter') if pitch is not None else None
                is_chord = note.find('chord') is not None  # <chord/> is an empty element: must test against None
                if pitch is not None:
                    step = pitch.find('step').text
                    alter = int(alter_el.text) if alter_el is not None else 0
                    octv = int(pitch.find('octave').text)
                    midi = STEP_SEMI[step] + alter + (octv + 1) * 12
                    onset = last[staff] if is_chord else cur[staff]
                    onset_map[(staff, onset)].append(midi)
                    st['notes'] += 1
                    (st['lh'] if (all_to_lh or staff == '2') else st['rh']).append(midi)
                    pc = step + ('-' if alter == -1 else ('+' if alter == 1 else '0'))
                    if pc_set and pc not in pc_set:
                        st['out_of_key'] += 1
                if not is_chord:
                    last[staff] = cur[staff]
                    cur[staff] += dur
            for k, v in onset_map.items():
                st['onsets'] += 1
                if len(v) >= 3:
                    st['onsets_ge3'] += 1

    # segment beats counted from the first part's measure numbers
    for meas in part.findall('measure'):
        mnum = int(meas.get('number'))
        s = seg_of(mnum)
        if s is not None:
            seg_stat[s]['beats'] += per_measure
    # multi-part support: first part = melody side (RH), remaining parts all to accompaniment side
    all_parts = root.findall('part')
    scan(all_parts[0], all_to_lh=False)
    for p in all_parts[1:]:
        scan(p, all_to_lh=True)

    print(f'═══ 张力账 — {path.split("/")[-1]} ═══')
    print(f'{"段":>7} | {"每拍发音数":>8} | {"RH均值":>6} | {"LH均值":>6} | {"三音+占比":>7} | {"离调":>4}')
    for s in SEGS:
        st = seg_stat[s]
        dens = st['notes'] / st['beats']
        rh = sum(st['rh']) / len(st['rh']) if st['rh'] else 0
        lh = sum(st['lh']) / len(st['lh']) if st['lh'] else 0
        ratio = st['onsets_ge3'] / st['onsets'] if st['onsets'] else 0
        print(f'm{s[0]:>2}-{s[1]:<2} | {dens:>8.1f} | {rh:>6.1f} | {lh:>6.1f} | {ratio:>7.0%} | {st["out_of_key"]:>4}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    pc = set(sys.argv[2].split(',')) if len(sys.argv) >= 3 and sys.argv[2] else DEFAULT_PC
    segs = None
    if len(sys.argv) >= 4:
        segs = []
        for part_str in sys.argv[3].split(','):
            a, b = part_str.split('-')
            segs.append((int(a), int(b)))
    main(sys.argv[1], pc, segs)
