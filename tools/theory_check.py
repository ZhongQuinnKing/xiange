#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
theory_check — 乐理错检器（乐理解读层）

模型认字，知识库读通。谱面出来先过乐理关：机器能机械检的乐理错当场报，
人（用户）只管艺术判断——这条分工写死。

规则清单 v1（来源：知识库 20-和声 / 30-曲式 / 10-乐理与记谱 / 61-旋律织体；2026-10-10）：

  E1 声部交叉   —— 两个声部同拍，低声部跑到高声部上面（严重）
                   设计性交叉（主客易位段、织体/彩饰声部穿行全音域）可用参数放行：
                   --e1-exempt 声部名（整曲豁免涉该声部的配对）、--e1-range 起-止
                   （小节段豁免，可多次）；放行照实留痕在报告头，未匹配的声部名照报
  E2 和弦音集   —— 同拍音高集合构成超出可能的音簇（四度叠置以上）[?] 待知识库细校，先只报强八度不报
  E3 平行五八度 —— 两声部连续两拍同向而行，且连续构成纯五度或纯八度（严重）
  E4 跨度过大   —— 同手同时发音超过默认可及上限（20 半音＝大十三度，--span 可调）（严重）
  E5 声部密度骤降 —— 持续和弦（≥2 拍、≥2 音）之后紧跟的发音点，音数骤降 ≥2（轻，待裁）
                     专抓"音类在、声部掉"的成组内声部缺失：和弦组成音类由他声部/
                     他八度顶班，音类级检查天生放行，本规则看同一手内音数守恒
  W1 声部重叠   —— 同声部内前音尚未结束、后音又起且高于前音的进行（轻）
  W2 小节时值   —— 小节内音符时值总和与拍号不符（除弱起小节）（轻）

输出：标准体检卡（规则ID 严重度 小节 详情），可与 omr_eval 报告卡并列成册。

用法:
    python3 theory_check.py <文件.musicxml|.mid|.krn>
    python3 theory_check.py <文件> --json 结果.json
    python3 theory_check.py <文件> --e1-range 9-12            # 设计段豁免 E1
    python3 theory_check.py <文件> --e1-exempt "Pipa,Guzheng" # 声部整曲豁免 E1
"""
import sys
import os
import json
import argparse
from collections import OrderedDict

from m21_cache import parse_cached, iter_notes_fast


SPAN_LIMIT = 20  # 默认可及上限：大十三度 = 20 半音（2026-10-10 改为面向用户（全球）的宽容默认；--span 可调）
E5_MIN_DUR = 2.0  # E5：持续和弦最短时值（四分音符数）＝2 拍
E5_DROP = 2       # E5：音数骤降阈值
FINDINGS = []    # (sev, code, measure, desc)
E1_EXEMPT = []   # --e1-exempt：整曲豁免 E1 的声部名（涉该声部的配对不报）
E1_RANGES = []   # --e1-range：豁免 E1 的小节区间 [(起, 止)]（设计段）
E1_NOTES = []    # E1 豁免的透明留痕（参数未匹配声部名等）


def add(sev, code, measure, desc):
    FINDINGS.append((sev, code, measure, desc))


def perfect_class(i):
    """音程的纯类别：0=纯八度类(12)，7=纯五度类，None=其他"""
    if i in (0, 12, -12, 24, -24):
        return '8ve'
    if i in (7, -7, 19, -19):
        return '5th'
    return None


def check_file(path):
    score = parse_cached(path)
    parts = list(score.parts)
    if not parts:
        print('无谱表')
        return

    # Per voice: measure -> [(onset, pitches_sorted, dur, offset)]
    part_events = OrderedDict()
    _seen = {}
    for pi, ps in enumerate(parts):
        name = ps.partName or f'P{pi + 1}'
        # [local adaptation 2026-10-11] guard same-named voices (single part split into two staves)
        if str(name) in _seen:
            _seen[str(name)] += 1
            name = f'{name}#{_seen[str(name)]}'
        else:
            _seen[str(name)] = 1
        evs = OrderedDict()
        for mi, meas in enumerate(ps.getElementsByClass('Measure'), 1):
            mno = meas.number
            if not isinstance(mno, int):
                try:
                    mno = int(''.join(ch for ch in str(mno) if ch.isdigit()) or 0)
                except ValueError:
                    mno = 0
            # Missing/duplicate numbers fall back to sequential position (fixed 2026-10-13: number-keying collapsed unnumbered files to the last measure alone,
            # once making a whole piece check only its last measure and falsely report "clean")
            if mno <= 0 or mno in evs:
                mno = mi
            lst = []
            seen = set()
            for el in iter_notes_fast(meas):
                if el.isRest:
                    continue
                ps_list = [n.pitch.midi for n in el.notes] if el.isChord else (
                    [el.pitch.midi] if el.pitch is not None else [])
                if not ps_list:
                    continue
                key = (round(float(el.offset), 4), tuple(sorted(ps_list)), float(el.quarterLength))
                if key in seen:
                    continue
                seen.add(key)
                lst.append((key[0], list(key[1]), key[2]))
            evs[mno] = lst
        part_events[name] = evs

    names = list(part_events.keys())

    # Hand detection: voice names containing RH/right/left etc. decide who should sit higher
    def is_lower_staff(n):
        s = n.lower()
        return ('lh' in s) or ('left' in s) or ('低' in s) or ('bass' in s) or ('b' == s)

    lower_staffs = [n for n in names if is_lower_staff(n)]
    upper_staffs = [n for n in names if n not in lower_staffs]
    if not lower_staffs and len(names) >= 2:
        # No hand marks: follow staff order, first is high, the rest low
        upper_staffs = [names[0]]
        lower_staffs = names[1:]

    # -- E4 unplayable same-beat span + E2 tone clusters -------------
    for name, evs in part_events.items():
        for mno, lst in evs.items():
            for onset, ps, dur in lst:
                if len(ps) > 1:
                    span = ps[-1] - ps[0]
                    if span > SPAN_LIMIT:
                        add('严重', 'E4', mno,
                            f'{name} 同拍跨度 {span} 半音（超默认可及上限 {SPAN_LIMIT}）：{ps}')

    # -- E1 voice crossing (the upper voice below the lower, or intersecting) -------
    #    designed crossings (hand-swap passages / texture weaves) pass via parameter; passes are logged, unmatched names still reported
    if E1_EXEMPT:
        unmatched = [n for n in E1_EXEMPT if n not in part_events]
        if unmatched:
            E1_NOTES.append(
                f'豁免声部名未匹配：{"、".join(unmatched)}；本谱声部＝{"、".join(names)}')
    if upper_staffs and lower_staffs:
        for lo_name in lower_staffs:
            for hi_name in upper_staffs:
                if lo_name in E1_EXEMPT or hi_name in E1_EXEMPT:
                    continue
                lo_evs, hi_evs = part_events[lo_name], part_events[hi_name]
                for mno in set(lo_evs) & set(hi_evs):
                    if any(a <= mno <= b for a, b in E1_RANGES):
                        continue
                    lo_map = {o: p for o, p, d in lo_evs[mno]}
                    hi_map = {o: p for o, p, d in hi_evs[mno]}
                    for onset in set(lo_map) & set(hi_map):
                        lmn = min(lo_map[onset]); hmn = min(hi_map[onset])
                        if lmn > hmn:
                            add('严重', 'E1', mno,
                                f'{lo_name}({lmn}) 高于 {hi_name}({hmn})，交叉 {lmn - hmn} 半音')

    # -- E3 parallel fifths/octaves (cross-voice, judged on the whole-piece timeline, continuing across measures) ------
    if upper_staffs and lower_staffs:
        for lo_name in lower_staffs:
            for hi_name in upper_staffs:
                a_evs, b_evs = part_events[hi_name], part_events[lo_name]
                # Whole-piece timeline: (measure, onset) -> pitches
                a_tl = []
                b_tl = []
                for mno in sorted(a_evs):
                    for o, p, d in a_evs[mno]:
                        a_tl.append(((mno, o), p))
                for mno in sorted(b_evs):
                    for o, p, d in b_evs[mno]:
                        b_tl.append(((mno, o), p))
                a_map = OrderedDict(a_tl)
                b_map = OrderedDict(b_tl)
                common = sorted(set(a_map) & set(b_map))
                for k in range(len(common) - 1):
                    key1, key2 = common[k], common[k + 1]
                    # Only note-vs-note is checked (chords would need set-based counterpoint; deferred)
                    if len(a_map[key1]) != 1 or len(b_map[key1]) != 1:
                        continue
                    if len(a_map[key2]) != 1 or len(b_map[key2]) != 1:
                        continue
                    a1, b1 = a_map[key1][0], b_map[key1][0]
                    a2, b2 = a_map[key2][0], b_map[key2][0]
                    d1 = a2 - a1
                    d2 = b2 - b1
                    if d1 == 0 or d2 == 0:
                        continue
                    if (d1 > 0) != (d2 > 0):
                        continue  # 反向，不构成平行
                    c1 = perfect_class(abs(a1 - b1))
                    c2 = perfect_class(abs(a2 - b2))
                    if c1 and c2 and c1 == c2:
                        add('严重', 'E3', key2[0],
                            f'{hi_name} 与 {lo_name} 连续同向构成平行{("八度" if c1 == "8ve" else "五度")}'
                            f'（{a1}/{b1} → {a2}/{b2}）')

    # -- E5 sudden voice-density drop (same-hand note-count conservation; grouped inner-voice loss where pitch classes remain) --
    # Criterion: in one voice and measure, after a multi-note chord (>=2 notes) sustained >= 2 beats
    #       the next attack has >= 2 fewer notes than the chord.
    # Rationale: a sustained chord (block or rolled) means the voice is in a multi-note texture; the next attack should continue
    #       the same texture (chord change or restatement). Dropping to one or two notes is a typical sign of grouped inner-voice loss in rolled/block textures;
    #       the missing chord tones often remain (covered by another voice or octave), so pitch-class checks pass,
    #       hence this separate same-hand note-count rule.
    # Edge: a legal monophonic melody after a sustained chord (e.g. waltz "chord + single note" cadences) also fires
    #       -- it is a hint, not a verdict, so it is minor (spot-checkable) and never auto-edits the score.
    for name, evs in part_events.items():
        for mno, lst in evs.items():
            lst_sorted = sorted(lst, key=lambda x: x[0])
            for k in range(len(lst_sorted) - 1):
                o1, ps1, d1 = lst_sorted[k]
                o2, ps2, d2 = lst_sorted[k + 1]
                n1 = len(set(ps1))     # 按音高去重计数：同音重复是识别毛刺，不当事部
                if n1 < 2 or d1 < E5_MIN_DUR - 1e-6:
                    continue
                if o2 <= o1 + 1e-6:
                    continue
                n2 = len(set(ps2))
                if n1 - n2 >= E5_DROP:
                    add('轻', 'E5', mno,
                        f'{name} 持续和弦 {ps1}（{d1} 拍）后骤降为 {ps2}'
                        f'（{n1}→{n2} 音）')

    # -- W1 note overlap: a new attack starts inside the previous note's span (potential crossing/stacking)
    #     new note entirely above the previous = suspect overlap (minor); entirely inside = normal continuation, not reported
    for name, evs in part_events.items():
        for mno, lst in evs.items():
            lst_sorted = sorted(lst, key=lambda x: x[0])
            for k in range(len(lst_sorted) - 1):
                o1, ps1, d1 = lst_sorted[k]
                o2, ps2, d2 = lst_sorted[k + 1]
                if o2 < o1 + d1 - 1e-6 and min(ps2) > max(ps1):
                    add('轻', 'W1', mno,
                        f'{name} 交叠：{ps1}（长{d1}）未完处上层起 {ps2}')

    return score


def check_measure_lengths(score):
    """W2：小节时值 vs 拍号（弱起小节、变拍号宽容处理）"""
    prev_ts = None
    for ps in score.parts:
        for meas in ps.getElementsByClass('Measure'):
            els = list(meas.recurse().notesAndRests)
            if not els:
                continue
            ts = meas.timeSignature
            if ts is None:
                ts = prev_ts
            else:
                prev_ts = ts
            if ts is None:
                continue
            expect = ts.barDuration.quarterLength
            total = sum(float(el.quarterLength) for el in els)
            # Threshold >= 1 beat: a difference of exactly 1.0 (e.g. a 5-beat measure in 4/4) must also report --
            # the old strict > 1.0 missed the most typical case, a full extra beat
            if abs(total - expect) >= 1.0 - 1e-6 and total > 0.5:
                add('轻', 'W2', meas.number,
                    f'{ps.partName or "谱表"} 小节时值 {total} ≠ 拍号 {expect}')


def build_report(path):
    FINDINGS.clear()
    E1_NOTES.clear()
    score = check_file(path)
    if score is None:
        return None
    check_measure_lengths(score)
    code_names = {'E1': '声部交叉', 'E2': '和弦音集', 'E3': '平行五八度',
                  'E4': '跨度过大', 'E5': '声部密度骤降',
                  'W1': '声部重叠', 'W2': '小节时值'}
    order = {'严重': 0, '轻': 1}
    findings = sorted(FINDINGS, key=lambda f: (order.get(f[0], 9), f[2], f[1]))
    lines = []
    lines.append(f'═══ 乐理体检卡 — {os.path.basename(path)} ═══')
    hard = [f for f in findings if f[0] == '严重']
    soft = [f for f in findings if f[0] == '轻']
    lines.append(f'严重 {len(hard)} 处｜轻 {len(soft)} 处')
    if E1_EXEMPT or E1_RANGES:
        ex = '、'.join(E1_EXEMPT) if E1_EXEMPT else '无'
        rg = '、'.join(f'{a}-{b}' for a, b in E1_RANGES) if E1_RANGES else '无'
        lines.append(f'E1 豁免（参数）：声部〔{ex}〕；小节〔{rg}〕；豁免处不报，其余规则不受影响')
    lines.extend(E1_NOTES)
    lines.append('')
    if not findings:
        lines.append('干净：无症状（注意本卡只查机械可检项，不含艺术判断）')
    for sev, code, mno, desc in findings:
        lines.append(f'  [{sev}] {code} {code_names.get(code, "")} m{mno}: {desc}')
    lines.append('')
    lines.append('口径：严重＝机械可判的乐理错（人无需再看）／轻＝可疑点（人可抽验）')
    lines.append('注：平行五度在流行织体里可能是有意的〔[?] 需听感判断，人裁〕')
    lines.append('注：E5 声部密度骤降是启发式（同手音数守恒），合法织体切换也会触发——'
                 '只作待裁提示，不作自动改谱依据')
    return '\n'.join(lines), findings


def main():
    ap = argparse.ArgumentParser(description='乐理错检器（知识库驱动的机械检）')
    ap.add_argument('file', help='MusicXML/MIDI')
    ap.add_argument('--json', help='结果写 JSON')
    ap.add_argument('--span', type=int, default=None, help='可及跨度上限（半音），默认 20（大十三度，面向用户可调）')
    ap.add_argument('--e1-exempt', default=None,
                    help='E1 豁免的声部名，逗号分隔（整曲；照体检卡显示的声部名写，如 "Pipa,Guzheng"）')
    ap.add_argument('--e1-range', action='append', default=None, metavar='起-止',
                    help='E1 豁免的小节区间（如 9-12；可多次，或逗号并列 9-12,15）')
    args = ap.parse_args()
    global SPAN_LIMIT, E1_EXEMPT, E1_RANGES
    if args.span:
        SPAN_LIMIT = args.span
    if args.e1_exempt:
        E1_EXEMPT = [x.strip() for x in args.e1_exempt.split(',') if x.strip()]
    for spec in (args.e1_range or []):
        for seg in str(spec).split(','):
            seg = seg.strip()
            if not seg:
                continue
            segs = seg.split('-', 1)
            try:
                a = int(segs[0])
                b = int(segs[1]) if len(segs) == 2 else a
            except ValueError:
                ap.error(f'--e1-range 格式应为「起-止」或单节号：{seg}')
            if a > b:
                a, b = b, a
            E1_RANGES.append((a, b))
    if not os.path.exists(args.file):
        sys.stderr.write(f'读谱失败：{args.file} 不存在（参数为 MusicXML/MIDI 文件路径）\n')
        sys.exit(2)
    res = build_report(args.file)
    if res is None:
        sys.exit(1)
    text, findings = res
    print(text)
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump([{'sev': s, 'code': c, 'measure': m, 'desc': d}
                       for s, c, m, d in findings], f, ensure_ascii=False, indent=1)
        print(f'（JSON 已写 {args.json}）')


if __name__ == '__main__':
    main()
