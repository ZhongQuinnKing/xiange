#!/usr/bin/env python3
"""
score_doctor — 扒谱修正台

用法:
    python3 score_doctor.py inspect <文件.mid|.musicxml|.xml>
    python3 score_doctor.py fix <输入> <输出.musicxml>

inspect: 读谱体检 —— 声部/音域/异常点清单，输出到终端
fix:     修整导出 —— 时值量化到常规音值、去重叠、出干净 MusicXML 给 Dorico

原则：只动时值和重叠，不改音高。音高的错要人来判，工具不擅自"修音"。
"""
import sys
import os
from collections import Counter

from music21 import converter, stream, note, chord, tempo as m21tempo, meter

STD_DURS = [4.0, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.375, 0.25, 0.125, 0.0625]
DUR_NAMES = {4.0: '全音符', 3.0: '附点二分', 2.0: '二分', 1.5: '附点四分', 1.0: '四分',
             0.75: '附点八分', 0.5: '八分', 0.375: '附点十六分', 0.25: '十六分',
             0.125: '三十二分', 0.0625: '六十四分'}

SPAN_LIMIT = 16  # 手型上限：大十度。编配常用最大跨度为十度，超过就是弹不了的谱（2026-09-19 定）

_SIMPLE_DEG = {0: (1, '纯'), 1: (2, '小'), 2: (2, '大'), 3: (3, '小'), 4: (3, '大'), 5: (4, '纯'),
               6: (4, '增'), 7: (5, '纯'), 8: (6, '小'), 9: (6, '大'), 10: (7, '小'), 11: (7, '大')}


def interval_name(semi):
    """半音数 → 音程名，如 16 → 大十度"""
    if semi <= 0:
        return '同音'
    octs, rem = divmod(semi, 12)
    deg, qual = _SIMPLE_DEG[rem]
    return f"{qual}{deg + 7 * octs}度"


def span_check(parts):
    """同时发音的音最大跨度。返回 [(声部, offset, 半音跨度, 音数)]，只列超限的。"""
    hits = []
    for name, items in parts.items():
        by_off = {}
        for off, el in items:
            ps = el.pitches if isinstance(el, chord.Chord) else [el.pitch]
            by_off.setdefault(round(off, 3), []).extend(ps)
        for off, ps in by_off.items():
            mids = [p.midi for p in ps]
            if len(mids) > 1 and max(mids) - min(mids) > SPAN_LIMIT:
                hits.append((name, off, max(mids) - min(mids), len(mids)))
    return hits


def nearest_std(q):
    return min(STD_DURS, key=lambda s: abs(s - q))


def load(path):
    return converter.parse(path)


def parts_of(score):
    """返回 {声部名: [(offset, 音符对象)]}，兼容单声部文件和总谱"""
    parts = {}
    src = score.parts if score.parts else [score]
    for i, p in enumerate(src):
        name = p.partName or getattr(p, 'id', None) or f'声部{i+1}'
        items = []
        for el in p.recurse().notesAndRests:
            if isinstance(el, (note.Note, chord.Chord)):
                items.append((float(el.offset), el))
        parts[str(name)] = items
    return parts


def inspect(path):
    score = load(path)
    print(f"\n{'='*56}")
    print(f"文件: {os.path.basename(path)}")
    try:
        mts = score.metronomeMarkBoundaries()
        if mts:
            print(f"速度: {mts[0][2].numberQuarterBPM:.0f} BPM")
    except Exception:
        pass
    ts = score.recurse().getElementsByClass(meter.TimeSignature)
    if ts:
        print(f"拍号: {ts[0].ratioString}")
    ks = score.recurse().getElementsByClass('KeySignature')
    if ks:
        sh = ks[0].sharps
        print(f"调号: {sh} 升/降" + ("（无升降）" if sh == 0 else ""))
    print(f"总小节: {len(score.parts[0].getElementsByClass('Measure')) if score.parts else '?'}")

    parts = parts_of(score)
    issues = []

    for name, items in parts.items():
        if not items:
            continue
        pitches = [el.pitch.midi for _, el in items if isinstance(el, note.Note)]
        chords = [el for _, el in items if isinstance(el, chord.Chord)]
        print(f"\n--- 声部: {name} ---")
        print(f"  音符 {len(items)} 个（含和弦 {len(chords)} 个）")
        if pitches:
            print(f"  音域: {min(pitches)} - {max(pitches)} (跨度 {max(pitches)-min(pitches)} 半音)")
            # 单音声部：看相邻跳进
            if len(pitches) > 4 and len(chords) == 0:
                jumps = [abs(pitches[i] - pitches[i-1]) for i in range(1, len(pitches))]
                big = [(i, pitches[i-1], pitches[i]) for i, j in enumerate(jumps) if j >= 12]
                if big:
                    issues.append(f"{name}: {len(big)} 处相邻音超八度跳进，疑似八度误判（首处 {big[0][1] if big else ''}→{big[0][2] if big else ''}）")
                    print(f"  ⚠ 超八度跳进 {len(big)} 处")
        # 时值分布
        durs = Counter(round(float(el.quarterLength), 3) for _, el in items)
        odd = {d: c for d, c in durs.items() if d not in [round(x, 3) for x in STD_DURS] and c >= 2}
        if odd:
            odd_top = sorted(odd.items(), key=lambda x: -x[1])[:4]
            issues.append(f"{name}: 非常规时值 {[(d, c) for d, c in odd_top]}（疑似量化不准）")
            print(f"  ⚠ 非常规时值: {odd_top}")

    # 跨声部重叠（同一时刻同一声部内两音重叠）
    for name, items in parts.items():
        ovs = 0
        srt = sorted(items, key=lambda x: x[0])
        for i in range(1, len(srt)):
            prev_off, prev_el = srt[i-1]
            if prev_off + float(prev_el.quarterLength) > srt[i][0] + 0.01:
                ovs += 1
        if ovs > 3:
            issues.append(f"{name}: {ovs} 处音符重叠（同声部内音没有正确断开）")
            print(f"  ⚠ {name} 有 {ovs} 处自重叠")

    # 和弦密度
    dense = 0
    for name, items in parts.items():
        for _, el in items:
            if isinstance(el, chord.Chord) and len(el.pitches) > 6:
                dense += 1
    if dense:
        issues.append(f"超过 6 音的和弦 {dense} 处（疑似把多声部混进一个和弦）")

    # 手型跨度：编配常用最大跨度为十度，超了就是弹不了的
    span_hits = span_check(parts)
    if span_hits:
        span_hits.sort(key=lambda x: -x[2])
        worst = span_hits[0]
        issues.append(f"{len(span_hits)} 处同时发音超十度，弹不了（最宽 {interval_name(worst[2])}，"
                      f"{worst[0]} 第 {worst[1]:.2f} 拍处）——需改转位或分解")
        print(f"  ⚠ 超十度跨度 {len(span_hits)} 处（最宽 {interval_name(worst[2])}）")

    print(f"\n{'='*56}")
    if issues:
        print(f"发现 {len(issues)} 类可疑点：")
        for i, s in enumerate(issues, 1):
            print(f"  {i}. {s}")
        print("\n建议：先听辨/看谱核对这几处，再跑 fix 导出。")
    else:
        print("未发现明显异常。")
    return issues


def fix(in_path, out_path):
    score = load(in_path)
    fixed_dur = 0
    trimmed = 0

    # 先量化：扒谱出的零碎时值里既有普通音也有三连音，
    # 同时保留 2/3/4 分法，否则三连音会被吸到普通音值上，节奏整个错乱
    try:
        score.quantize([2, 3, 4], processOffsets=True, processDurations=True, inPlace=True)
    except Exception as e:
        print(f"量化跳过（{str(e)[:50]}），直接走时值吸附")

    for p in (score.parts if score.parts else [score]):
        for el in p.recurse().notesAndRests:
            if not isinstance(el, (note.Note, chord.Chord)):
                continue
            q = float(el.quarterLength)
            if q <= 0:
                continue
            nq = nearest_std(q)
            if abs(nq - q) <= 0.14 * q and nq != q:   # 偏差小于 14% 才吸附
                el.quarterLength = nq
                fixed_dur += 1
            elif q > 0.05 and nq != q:
                el.quarterLength = nq
                fixed_dur += 1

        # 同声部内重叠：把前一个音截短到后一个音起点
        items = [el for el in p.recurse().notes]
        srt = sorted(items, key=lambda e: float(e.offset))
        for i in range(1, len(srt)):
            prev = srt[i-1]
            if float(prev.offset) + float(prev.quarterLength) > float(srt[i].offset) + 0.01:
                newq = max(0.0625, float(srt[i].offset) - float(prev.offset))
                prev.quarterLength = nearest_std(newq) if newq >= 0.125 else 0.125
                trimmed += 1

    span_hits = span_check(parts_of(score))
    score.write('musicxml', fp=out_path)
    print(f"时值修整 {fixed_dur} 处，去重叠 {trimmed} 处")
    if span_hits:
        print(f"⚠ 仍有 {len(span_hits)} 处同时发音超十度，Dorico 里要人工改成转位/分解")
    print(f"已导出: {out_path}")
    print("下一步：Dorico 导入这个文件 → 校对 → 存 .dorico / 出 PDF")


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == 'inspect':
        inspect(sys.argv[2])
    elif cmd == 'fix':
        fix(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'out.musicxml')
    else:
        print(__doc__)
