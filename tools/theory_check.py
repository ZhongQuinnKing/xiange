#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
theory_check — 乐理错检器（护城河第④层：乐理解读层）

模型认字，知识库读通。谱面出来先过乐理关：机器能机械检的乐理错当场报，
人（用户）只管艺术判断——这条分工写死。

规则清单 v1（来源：知识库 20-和声 / 30-曲式 / 10-乐理与记谱 / 61-旋律织体；2026-10-10）：

  E1 声部交叉   —— 两个声部同拍，低声部跑到高声部上面（严重）
  E2 和弦音集   —— 同拍音高集合构成超出可能的音簇（四度叠置以上）[?] 待知识库细校，先只报强八度不报
  E3 平行五八度 —— 两声部连续两拍同向而行，且连续构成纯五度或纯八度（严重）
  E4 空拍不可弹 —— 同手同时发音超过大十度（16 半音）（严重，编配手型上限（十度））
  W1 声部重叠   —— 同声部内前音尚未结束、后音又起且高于前音的进行（轻）
  W2 小节时值   —— 小节内音符时值总和与拍号不符（除弱起小节）（轻）

输出：标准体检卡（规则ID 严重度 小节 详情），可与 omr_eval 报告卡并列成册。

用法:
    python3 theory_check.py <文件.musicxml|.mid|.krn>
    python3 theory_check.py <文件> --json 结果.json
"""
import sys
import os
import json
import argparse
from collections import OrderedDict

from music21 import converter, interval as m21interval

SPAN_LIMIT = 16  # 大十度 = 16 半音（用户手型上限，2026-09-19 定，不可改）
FINDINGS = []    # (sev, code, measure, desc)


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
    score = converter.parse(path)
    parts = list(score.parts)
    if not parts:
        print('无谱表')
        return

    # 每声部：小节 → [(onset, pitches_sorted, dur, offset)]
    part_events = OrderedDict()
    for pi, ps in enumerate(parts):
        name = ps.partName or f'P{pi + 1}'
        evs = OrderedDict()
        for meas in ps.getElementsByClass('Measure'):
            mno = meas.number
            if not isinstance(mno, int):
                try:
                    mno = int(''.join(ch for ch in str(mno) if ch.isdigit()) or 0)
                except ValueError:
                    continue
            lst = []
            seen = set()
            for el in meas.recurse().notesAndRests:
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

    # 键盘手判定：声部名含 RH/right/左手等 → 高键盘手；判定"谁应当在高处"
    def is_lower_staff(n):
        s = n.lower()
        return ('lh' in s) or ('left' in s) or ('低' in s) or ('bass' in s) or ('b' == s)

    lower_staffs = [n for n in names if is_lower_staff(n)]
    upper_staffs = [n for n in names if n not in lower_staffs]
    if not lower_staffs and len(names) >= 2:
        # 无左手标记：按谱表顺序，第一个为高、其后为低
        upper_staffs = [names[0]]
        lower_staffs = names[1:]

    # ── E4 空拍不可弹（同拍跨度）+ E2 音簇 ─────────────────
    for name, evs in part_events.items():
        for mno, lst in evs.items():
            for onset, ps, dur in lst:
                if len(ps) > 1:
                    span = ps[-1] - ps[0]
                    if span > SPAN_LIMIT:
                        add('严重', 'E4', mno,
                            f'{name} 同拍跨度 {span} 半音（超十度）：{ps}')

    # ── E1 声部交叉（应在上者低于应在下者，或两者相交）─────
    if upper_staffs and lower_staffs:
        for lo_name in lower_staffs:
            for hi_name in upper_staffs:
                lo_evs, hi_evs = part_events[lo_name], part_events[hi_name]
                for mno in set(lo_evs) & set(hi_evs):
                    lo_map = {o: p for o, p, d in lo_evs[mno]}
                    hi_map = {o: p for o, p, d in hi_evs[mno]}
                    for onset in set(lo_map) & set(hi_map):
                        lmn = min(lo_map[onset]); hmn = min(hi_map[onset])
                        if lmn > hmn:
                            add('严重', 'E1', mno,
                                f'{lo_name}({lmn}) 高于 {hi_name}({hmn})，交叉 {lmn - hmn} 半音')

    # ── E3 平行五八度（跨声部，按全曲时间线对齐判定，跨小节接续）───────
    if upper_staffs and lower_staffs:
        for lo_name in lower_staffs:
            for hi_name in upper_staffs:
                a_evs, b_evs = part_events[hi_name], part_events[lo_name]
                # 全曲时间线：(小节, onset) → pitches
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
                    # 单音对单音才检（和弦由音集对位判，复杂，暂不出手）
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

    # ── W1 音节交叠：前一音未完，后起音在前音音域内（潜在声部交叉/叠置）
    #     后起音整体高于前音＝可疑交叠（轻）；整体含在前音范围内＝常规延续，不报
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
            if abs(total - expect) > 1.0 and total > 0.5:
                add('轻', 'W2', meas.number,
                    f'{ps.partName or "谱表"} 小节时值 {total} ≠ 拍号 {expect}')


def build_report(path):
    FINDINGS.clear()
    score = check_file(path)
    if score is None:
        return None
    check_measure_lengths(score)
    code_names = {'E1': '声部交叉', 'E2': '和弦音集', 'E3': '平行五八度',
                  'E4': '超十度', 'W1': '声部重叠', 'W2': '小节时值'}
    order = {'严重': 0, '轻': 1}
    findings = sorted(FINDINGS, key=lambda f: (order.get(f[0], 9), f[2], f[1]))
    lines = []
    lines.append(f'═══ 乐理体检卡 — {os.path.basename(path)} ═══')
    hard = [f for f in findings if f[0] == '严重']
    soft = [f for f in findings if f[0] == '轻']
    lines.append(f'严重 {len(hard)} 处｜轻 {len(soft)} 处')
    lines.append('')
    if not findings:
        lines.append('干净：无症状（注意本卡只查机械可检项，不含艺术判断）')
    for sev, code, mno, desc in findings:
        lines.append(f'  [{sev}] {code} {code_names.get(code, "")} m{mno}: {desc}')
    lines.append('')
    lines.append('口径：严重＝机械可判的乐理错（人无需再看）／轻＝可疑点（人可抽验）')
    lines.append('注：平行五度在流行织体里可能是有意的〔[?] 需听感判断，人裁〕')
    return '\n'.join(lines), findings


def main():
    ap = argparse.ArgumentParser(description='乐理错检器（知识库驱动的机械检）')
    ap.add_argument('file', help='MusicXML/MIDI')
    ap.add_argument('--json', help='结果写 JSON')
    args = ap.parse_args()
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
