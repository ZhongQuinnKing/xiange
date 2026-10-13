#!/usr/bin/env python3
"""
score_doctor — 扒谱修正台

用法:
    python3 score_doctor.py inspect <文件.mid|.musicxml|.xml>
    python3 score_doctor.py fix <输入> <输出.musicxml>

inspect: 读谱体检 —— 声部/音域/异常点清单，输出到终端
fix:     修整导出 —— 时值量化到常规音值、去重叠、出干净 MusicXML 给 Dorico
         安全约定：改前自动备份原文件为 <输入>.orig（只留第一份、不覆盖）；
         改后列出被改动音符明细（终端 + <输出>.changes.txt），破坏性动作不沉默；
         修后自检重叠不收敛会显式警告。修完请人工核对明细再采用。

原则：只动时值和重叠，不改音高。音高的错要人来判，工具不擅自"修音"。

坐标纪律：一切时间比较（重叠判据、跨度分组、截短）都用全局坐标
getOffsetInHierarchy。el.offset 是小节内局部坐标，跨小节混排会把"上一
小节末尾音"与"下一小节开头音"错排成相邻，对任何多小节文件系统性误报。
"""
import sys
import os
import shutil
from collections import Counter

from music21 import converter, note, chord, meter

STD_DURS = [4.0, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.375, 0.25, 0.125, 0.0625]
DUR_NAMES = {4.0: '全音符', 3.0: '附点二分', 2.0: '二分', 1.5: '附点四分', 1.0: '四分',
             0.75: '附点八分', 0.5: '八分', 0.375: '附点十六分', 0.25: '十六分',
             0.125: '三十二分', 0.0625: '六十四分'}

SPAN_LIMIT = 20  # 默认可及上限：大十三度 = 20 半音（2026-10-10 改，面向用户宽容默认，可按需调）

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


def floor_fit(space):
    """截短余量吸附：取不超过 space 的最大标准音值（防止就近吸附吸大后再生重叠）"""
    cand = [s for s in STD_DURS if s <= space + 1e-9]
    return max(cand) if cand else 0.0625


def find_overlaps(items):
    """同声部内真重叠：前音结束越过后音起点。

    items = [(全局offset, 元素)]。返回 [(前音, 后音, 前音offset, 后音offset)]。
    inspect 与 fix 共用这唯一判据，防止两处口径漂移（历史上正是两处
    口径不一致导致误报 + 误修）。
    """
    hits = []
    srt = sorted(items, key=lambda x: x[0])
    for i in range(1, len(srt)):
        prev_off, prev_el = srt[i - 1]
        next_off = srt[i][0]
        if prev_off + float(prev_el.quarterLength) > next_off + 0.01:
            hits.append((prev_el, srt[i][1], prev_off, next_off))
    return hits


def load(path):
    return converter.parse(path)


def parts_of(score):
    """返回 {声部名: [(全局offset, 音符对象)]}，兼容单声部文件和总谱

    offset 取全局坐标（getOffsetInHierarchy）——局部坐标会让跨小节的
    排序比较错位，对多小节文件系统性误报重叠。
    """
    parts = {}
    src = score.parts if score.parts else [score]
    _seen = {}
    for i, p in enumerate(src):
        name = p.partName or getattr(p, 'id', None) or f'声部{i+1}'
        # [本地适配 2026-10-11] 同名声部防塌陷（单 part 双谱表按谱表拆分后同名，字典会互相覆盖）
        if str(name) in _seen:
            _seen[str(name)] += 1
            name = f'{name}#{_seen[str(name)]}'
        else:
            _seen[str(name)] = 1
        items = []
        for el in p.recurse().notesAndRests:
            if isinstance(el, (note.Note, chord.Chord)):
                items.append((float(el.getOffsetInHierarchy(score)), el))
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

    # 同声部内重叠（真重叠：前音结束越过后音起点；全局坐标统一判据）
    for name, items in parts.items():
        ovs = find_overlaps(items)
        if ovs:
            issues.append(f"{name}: {len(ovs)} 处音符重叠（同声部内音没有正确断开）")
            print(f"  ⚠ {name} 有 {len(ovs)} 处自重叠")

    # 和弦密度
    dense = 0
    for name, items in parts.items():
        for _, el in items:
            if isinstance(el, chord.Chord) and len(el.pitches) > 6:
                dense += 1
    if dense:
        issues.append(f"超过 6 音的和弦 {dense} 处（疑似把多声部混进一个和弦）")

    # 跨度：默认可及上限（大十三度），超了提示核对
    span_hits = span_check(parts)
    if span_hits:
        span_hits.sort(key=lambda x: -x[2])
        worst = span_hits[0]
        issues.append(f"{len(span_hits)} 处同时发音跨度过大（最宽 {interval_name(worst[2])}，"
                      f"{worst[0]} 第 {worst[1]:.2f} 拍处）——需改转位或分解")
        print(f"  ⚠ 跨度过大 {len(span_hits)} 处（最宽 {interval_name(worst[2])}）")

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
    changes = []   # 被改动音符明细（字符串行）

    # 改前自动备份原文件（.orig 只留第一份，不覆盖）
    bak = in_path + '.orig'
    if os.path.exists(bak):
        print(f"原文件备份已存在（保留最初版）: {bak}")
    else:
        shutil.copy2(in_path, bak)
        print(f"原文件已备份: {bak}")

    def tag(el):
        """明细用标记：音名 + 全局位置（拍）"""
        nm = el.nameWithOctave if isinstance(el, note.Note) else f'和弦({len(el.pitches)}音)'
        return nm, float(el.getOffsetInHierarchy(score))

    # 量化前快照（量化是最沉默的一步，改动也要可见）
    all_els = [el for p in (score.parts if score.parts else [score])
               for el in p.recurse().notesAndRests
               if isinstance(el, (note.Note, chord.Chord))]
    snap = {id(el): (float(el.offset), float(el.quarterLength)) for el in all_els}

    # 先量化：扒谱出的零碎时值里既有普通音也有三连音，
    # 同时保留 2/3/4 分法，否则三连音会被吸到普通音值上，节奏整个错乱
    try:
        score.quantize([2, 3, 4], processOffsets=True, processDurations=True, inPlace=True)
    except Exception as e:
        print(f"量化跳过（{str(e)[:50]}），直接走时值吸附")

    quant_n = 0
    for el in all_els:
        s = snap.get(id(el))
        if s is None:
            continue
        if abs(s[1] - float(el.quarterLength)) > 1e-6 or abs(s[0] - float(el.offset)) > 1e-6:
            quant_n += 1
            if quant_n <= 5:
                nm, off = tag(el)
                changes.append(f"[量化] 全局{off:7.2f}拍 {nm}: 时值 {s[1]:.2f}→{float(el.quarterLength):.2f}")
    if quant_n > 5:
        changes.append(f"[量化] ……另有 {quant_n - 5} 个音被量化调整（合计 {quant_n}）")

    fixed_dur = 0
    trimmed = 0
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
                nm, off = tag(el)
                changes.append(f"[吸附] 全局{off:7.2f}拍 {nm}: 时值 {q:.3f}→{nq}")
            elif q > 0.05 and nq != q:
                el.quarterLength = nq
                fixed_dur += 1
                nm, off = tag(el)
                changes.append(f"[吸附] 全局{off:7.2f}拍 {nm}: 时值 {q:.3f}→{nq}")

        # 去重叠：统一判据（全局坐标）定位，前音截短不越过后音起点；
        # 截短量吸附用 floor（≤空间的标准值），防吸大后再生重叠
        items = [(float(el.getOffsetInHierarchy(score)), el) for el in p.recurse().notes]
        for prev_el, next_el, prev_off, next_off in find_overlaps(items):
            space = next_off - prev_off
            old_q = float(prev_el.quarterLength)
            new_q = floor_fit(space)
            if new_q >= old_q - 1e-9:
                continue   # 防御：空间不小于原时值（不该发生）
            prev_el.quarterLength = new_q
            trimmed += 1
            nm, off = tag(prev_el)
            n_nm, n_off = tag(next_el)
            changes.append(f"[去重叠] 全局{off:7.2f}拍 {nm}: 时值 {old_q:.2f}→{new_q}"
                           f"（被 {n_off:.2f} 拍起的 {n_nm} 顶住）")

    span_hits = span_check(parts_of(score))

    # 修后自检：同一判据重扫，不收敛必须可见
    left = []
    for p in (score.parts if score.parts else [score]):
        items = [(float(el.getOffsetInHierarchy(score)), el) for el in p.recurse().notes]
        left += find_overlaps(items)

    score.write('musicxml', fp=out_path)
    print(f"时值修整 {fixed_dur} 处，去重叠 {trimmed} 处")
    if changes:
        changes_path = out_path + '.changes.txt'
        with open(changes_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(changes) + '\n')
        print(f"—— 改动明细（共 {len(changes)} 条）——")
        for ln in changes[:12]:
            print('  ' + ln)
        if len(changes) > 12:
            print(f"  ……另 {len(changes) - 12} 条见 {changes_path}")
        print(f"  （全部明细已写入 {changes_path}）")
    if left:
        print(f"⚠ 修后自检：仍有 {len(left)} 处重叠未收敛，产物请人工核对（原文件备份在 {bak}）")
    else:
        print("修后自检：重叠 0 处（收敛）")
    if span_hits:
        print(f"⚠ 仍有 {len(span_hits)} 处同时发音跨度过大，Dorico 里要人工改成转位/分解")
    print(f"已导出: {out_path}")
    print("下一步：Dorico 导入这个文件 → 校对 → 存 .dorico / 出 PDF")


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    cmd = sys.argv[1]
    json_path = None
    if '--json' in sys.argv:
        i = sys.argv.index('--json')
        json_path = sys.argv[i + 1] if len(sys.argv) > i + 1 else None
        del sys.argv[i:i + 2]
    if cmd == 'inspect':
        import os as _os
        if not _os.path.exists(sys.argv[2]):
            sys.stderr.write(f'读谱失败：{sys.argv[2]} 不存在（参数为 MusicXML 文件路径）\n')
            sys.exit(2)
        msgs = inspect(sys.argv[2])
        if json_path:
            import json as _json
            with open(json_path, 'w', encoding='utf-8') as f:
                _json.dump({'file': sys.argv[2], 'issues': msgs,
                            'verdict': 'suspect' if msgs else 'clean'},
                           f, ensure_ascii=False, indent=1)
            print(f'（JSON 已写 {json_path}）')
    elif cmd == 'fix':
        fix(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'out.musicxml')
    else:
        print(__doc__)
        sys.exit(2)
