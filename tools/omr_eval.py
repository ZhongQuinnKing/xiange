#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
omr_eval — 统一评价引擎（口径标准 v1.0 的实体）

四个解析器（双读 md / 简谱 melody_v4 / MusicXML / 内嵌音符表）
→ 统一音符事件表 → 四级度量 → 标准报告卡

判据口径见同目录《口径标准.md》，本文件不另立说法。

用法:
    # Dual-read md vs MusicXML (engine output)
    python3 omr_eval.py --truth jp:/var/tmp/jp/pages/page1_data.md --engine mx:/var/tmp/b_rows/row_01.omr.musicxml

    # Numbered-score ground truth vs MusicXML (1=G)
    python3 omr_eval.py --truth jp:/path/truth.md --engine mx:/path/out.musicxml --key G

    # Pure structural check
    python3 omr_eval.py --engine mx:/path/out.musicxml --inspect
"""
import os
import re
import json
import argparse
from collections import OrderedDict, Counter

# -- pitch name -> semitone number ---------------------------------
_PC = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
# Numbered degree -> semitones above tonic (1 = tonic)
_DEGREE = {1: 0, 2: 2, 3: 4, 4: 5, 5: 7, 6: 9, 7: 11}
# Tonic name -> semitone number (the X in 1=X)
_KEYTONIC = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}


class NoteEvent:
    """统一音符事件：四级度量的最小单位"""
    __slots__ = ('measure', 'part', 'pitches', 'durs', 'flags')

    def __init__(self, measure, part, pitches, durs, flags=None):
        self.measure = measure      # 小节号（int）
        self.part = part            # 'RH'/'LH' 或声部名
        self.pitches = pitches      # 绝对音高（MIDI 数）列表，和弦为多个
        self.durs = durs            # 时长（拍，四分音符=1.0）列表，与 pitches 对齐
        self.flags = flags or []    # 'tie' / 'rest' / '?' 等标记


# ===============================================================
# Parsers
# ===============================================================

def parse_jp_md(path):
    """双读 md 格式：## mN 分段，RH:/LH: 行，[音名,...]:时值（(tie) 标记延音）"""
    events = []
    cur = None
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            m = re.match(r'^##\s*m(\d+)', line)
            if m:
                cur = int(m.group(1))
                continue
            if cur is None:
                continue
            for hand in ('RH', 'LH'):
                if line.startswith(hand + ':'):
                    body = line[len(hand) + 1:]
                    body = re.sub(r'（[^）]*）', '', body)        # 去中文括号注释
                    body = re.sub(r'\(tie\)', '~TIE~', body)     # 延音标记暂存
                    body = re.sub(r'\([^)]*\)', '', body)        # 去其余英文括号注释
                    # Only [note]:number or R:number are data (annotation [..] refs lack ':number' and filter out naturally)
                    for tok in re.finditer(r'(\[[A-Ga-g#b\d,\s?\-]*\]|R|~TIE~)\s*(?::\s*([0-9.]+))?', body):
                        raw = tok.group(1)
                        if raw == '~TIE~':
                            if events:
                                events[-1].flags.append('tie')
                            continue
                        if tok.group(2) is None:
                            continue
                        dur = float(tok.group(2))
                        if raw == 'R':
                            events.append(NoteEvent(cur, hand, [], [dur], ['rest']))
                            continue
                        names = [x.strip() for x in raw.strip('[]').split(',') if x.strip()]
                        ps, ds = [], []
                        for n in names:
                            pc = parse_note_name(n)
                            if pc is None:
                                continue
                            ps.append(pc)
                            ds.append(dur)
                        if ps:
                            events.append(NoteEvent(cur, hand, ps, ds, []))
    return events


def parse_note_name(n):
    """'F#3' → MIDI 数；'B1' → 35；带 '?' 丢弃"""
    if '?' in n:
        return None
    m = re.match(r'^([A-Ga-g])([#b-]?)(-?\d)$', n.strip())
    if not m:
        return None
    base = _PC[m.group(1).upper()]
    acc = {'#': 1, 'b': -1, '-': -1}.get(m.group(2), 0)
    octv = int(m.group(3))
    return (octv + 1) * 12 + base + acc


def parse_jianpu(path, key='G', base_octave=4):
    """简谱真值格式（melody_v4 一类）：{小节: [(音级, 时值), ...]}
    音级 '1'-'7'，前缀 b/#，后缀 +/- 八度，'0'=休止。
    返回 NoteEvent 列表（part='M' 单声部）。
    """
    # Safely load the MELODY dict via exec (that file is data-only, literals only)
    src = open(path, encoding='utf-8').read()
    m = re.search(r'MELODY\s*=\s*(\{.*?\n\})', src, re.S)
    if not m:
        raise ValueError('未找到 MELODY 字典')
    data = eval(m.group(1), {'__builtins__': {}})  # 纯字面量，安全
    tonic = _KEYTONIC[key]
    events = []
    for meas, items in sorted(data.items()):
        for sym, dur in items:
            if sym == '0':
                events.append(NoteEvent(meas, 'M', [], [dur], ['rest']))
                continue
            sm = re.match(r'^([b#]?)([1-7])([+-]?)$', sym)
            if not sm:
                continue
            acc = {'b': -1, '#': 1}.get(sm.group(1), 0)
            deg = int(sm.group(2))
            oct_shift = {'+': 12, '-': -12, '': 0}.get(sm.group(3), 0)
            midi = (base_octave + 1) * 12 + tonic + _DEGREE[deg] + acc + oct_shift
            events.append(NoteEvent(meas, 'M', [midi], [dur]))
    return events


def parse_musicxml(path):
    """MusicXML/MIDI → NoteEvent 列表（music21）"""
    import music21
    score = music21.converter.parse(path)
    events = []
    for ps in score.parts:
        pname = ps.partName or f'P{score.parts.index(ps)}'
        for meas in ps.getElementsByClass('Measure'):
            mnum = meas.number
            if not isinstance(mnum, int):
                try:
                    mnum = int(re.sub(r'\D', '', str(mnum)) or 0)
                except ValueError:
                    continue
            # Group within measure by onset
            at_onset = OrderedDict()
            for el in meas.recurse().notesAndRests:
                off = float(el.offset)
                at_onset.setdefault(off, []).append(el)
            for off, els in at_onset.items():
                pitches, durs, flags = [], [], []
                is_rest = all(el.isRest for el in els)
                for el in els:
                    if el.isRest:
                        continue
                    if el.isChord:
                        for n in el.notes:
                            if n.pitch is not None:
                                pitches.append(n.pitch.midi)
                                durs.append(float(el.quarterLength))
                    else:
                        if el.pitch is not None:
                            pitches.append(el.pitch.midi)
                            durs.append(float(el.quarterLength))
                    if getattr(el, 'tie', None) and el.tie.type != 'start':
                        flags.append('tie_cont')
                if is_rest and not pitches:
                    events.append(NoteEvent(mnum, pname, [], [float(els[0].quarterLength)], ['rest']))
                else:
                    events.append(NoteEvent(mnum, pname, pitches, durs, flags))
    return events


# ===============================================================
# Four-level metric
# ===============================================================

def pc_set(ev):
    return set(p % 12 for p in ev.pitches)


def is_rest(ev):
    return 'rest' in ev.flags and not ev.pitches


DUR_TOL_ABS = 0.26   # 绝对容差上限（一个十六分音符 = 0.25 拍）
DUR_TOL_REL = 0.15   # 相对容差：事件时长的 15%
DUR_TOL_FLOOR = 0.04  # 容差下限（浮点噪声，十六分音符级）


def dur_tol(d1, d2):
    """时值容差：随事件自身时长相对缩放，上限 0.26、下限 0.04。
    0.25↔0.25 判同（差 0）；0.5→0.25（差 25%）判不同；十六分量化噪声 0.01 判同。
    """
    return min(DUR_TOL_ABS, max(DUR_TOL_FLOOR, DUR_TOL_REL * max(d1, d2)))


def dur_equal(d1, d2):
    return abs(d1 - d2) <= dur_tol(d1, d2)


def align_measure(truth_evs, engine_evs):
    """小节内事件对齐：各自混声部按序，用在音高类集合上做贪心配对。
    返回 (pairs, truth_unmatched, engine_unmatched)
    """
    t_used = [False] * len(truth_evs)
    pairs = []
    t_un = []
    for e in engine_evs:
        if is_rest(e):
            continue
        epc = pc_set(e)
        best, best_score = None, 0
        for i, t in enumerate(truth_evs):
            if t_used[i] or is_rest(t):
                continue
            tpc = pc_set(t)
            inter = len(epc & tpc)
            if inter > best_score:
                best, best_score = i, inter
        if best is not None and best_score > 0:
            t_used[best] = True
            pairs.append((truth_evs[best], e))
    for i, t in enumerate(truth_evs):
        if not t_used[i] and not is_rest(t):
            t_un.append(t)
    e_un = [e for e in engine_evs if not is_rest(e)
            and e not in [p[1] for p in pairs]]
    return pairs, t_un, e_un


def _median_pitch(evs):
    vals = []
    for e in evs:
        if not is_rest(e) and e.pitches:
            vals.append(sum(e.pitches) / len(e.pitches))
    return (sorted(vals)[len(vals) // 2] if vals else 0)


def align_measure_by_part(truth_evs, engine_evs):
    """按声部优先配对（2026-10-10 夜立，修混声部串配假象）。
    两侧都 ≥2 声部时：按声部音域中位排序一一配对，组内走 align_measure；
    否则回退混声部（单声部场景与旧行为一致）。
    起因：BWV114 混声部贪心把引擎低音配到真值高音，58 处"八度差"实为 4。
    """
    from collections import OrderedDict as _OD
    t_parts, e_parts = _OD(), _OD()
    for t in truth_evs:
        t_parts.setdefault(t.part, []).append(t)
    for e in engine_evs:
        e_parts.setdefault(e.part, []).append(e)
    if len(t_parts) < 2 or len(e_parts) < 2:
        return align_measure(truth_evs, engine_evs)
    tp = sorted(t_parts.keys(), key=lambda k: _median_pitch(t_parts[k]))
    ep = sorted(e_parts.keys(), key=lambda k: _median_pitch(e_parts[k]))
    pairs, t_un, e_un = [], [], []
    n = min(len(tp), len(ep))
    for i in range(n):
        p, tu, eu = align_measure(t_parts[tp[i]], e_parts[ep[i]])
        pairs += p; t_un += tu; e_un += eu
    for k in tp[n:]:
        t_un += [x for x in t_parts[k] if not is_rest(x)]
    for k in ep[n:]:
        e_un += [x for x in e_parts[k] if not is_rest(x)]
    return pairs, t_un, e_un


def evaluate(truth_events, engine_events, label_truth='真值', label_engine='引擎',
             measure_range=None):
    """四级度量主函数。返回结果字典。measure_range=(lo,hi) 时只比该范围内的小节。"""
    if measure_range:
        lo, hi = measure_range
        truth_events = [e for e in truth_events if lo <= e.measure <= hi]
        engine_events = [e for e in engine_events if lo <= e.measure <= hi]
    t_by_m = OrderedDict()
    for e in truth_events:
        t_by_m.setdefault(e.measure, []).append(e)
    e_by_m = OrderedDict()
    for e in engine_events:
        e_by_m.setdefault(e.measure, []).append(e)

    result = {
        'label_truth': label_truth, 'label_engine': label_engine,
        'truth_total': sum(len(e.pitches) for e in truth_events if not is_rest(e)),
        'engine_total': sum(len(e.pitches) for e in engine_events if not is_rest(e)),
        'green': 0, 'yellow': 0, 'red': 0,
        'octave_diff': 0, 'pitch_exact': 0, 'pitch_matched': 0,
        'dur_same': 0, 'dur_total_err': 0, 'dur_split_err': 0,
        'measures_common': 0, 'measures_only_truth': 0, 'measures_only_engine': 0,
        'detail_red': [],
    }
    common = sorted(set(t_by_m) & set(e_by_m))
    result['measures_common'] = len(common)
    result['measures_only_truth'] = len(set(t_by_m) - set(e_by_m))
    result['measures_only_engine'] = len(set(e_by_m) - set(t_by_m))

    for m in common:
        pairs, t_un, e_un = align_measure_by_part(t_by_m[m], e_by_m[m])
        for t, e in pairs:
            tpc, epc = pc_set(t), pc_set(e)
            exact = (tpc == epc)
            if exact:
                # Octave check: compare octaves within the same pitch class
                t_oct = [(p % 12, p // 12) for p in t.pitches]
                e_oct = [(p % 12, p // 12) for p in e.pitches]
                if sorted(t_oct) != sorted(e_oct):
                    result['octave_diff'] += len(t.pitches)
                    result['red'] += 1
                    result['detail_red'].append((m, '八度', t.pitches, e.pitches))
                    continue
                result['pitch_exact'] += len(t.pitches)
                result['pitch_matched'] += len(t.pitches)
                # Duration level: compare total event length (standard v1.0: total-length errors and segmentation errors counted separately)
                ts, es = sum(t.durs), sum(e.durs)
                same = dur_equal(ts, es)
                if same:
                    result['green'] += 1
                    result['dur_same'] += 1
                else:
                    result['yellow'] += 1
                    if abs(ts - es) > 2 * dur_tol(ts, es):
                        result['dur_total_err'] += 1
                    else:
                        result['dur_split_err'] += 1
            else:
                # Partial-hit scoring (pitch-class intersection)
                inter = len(tpc & epc)
                result['pitch_matched'] += inter
                if inter > 0:
                    result['yellow'] += 1
                else:
                    result['red'] += 1
                result['detail_red'].append((m, '音高', t.pitches, e.pitches))
        # Unmatched: missed ground-truth note (engine dropped it)
        for t in t_un:
            result['red'] += 1
            result['detail_red'].append((m, '漏', t.pitches, []))
        for e in e_un:
            result['red'] += 1
            result['detail_red'].append((m, '多', [], e.pitches))
    return result


def report_card(result, title=''):
    """标准报告卡（口径标准 v1.0 固定格式）"""
    r = result
    n = r['green'] + r['yellow'] + r['red']
    lines = []
    lines.append(f'═══ 标准报告卡 {("— " + title) if title else ""} ═══')
    lines.append(f'真值: {r["label_truth"]}（{r["truth_total"]} 音）  ×  引擎: {r["label_engine"]}（{r["engine_total"]} 音）')
    lines.append('')
    if n:
        lines.append(f'音高级: 全音高类命中 {r["pitch_matched"]}/{r["truth_total"]}'
                     f' = {r["pitch_matched"]/max(1,r["truth_total"])*100:.1f}%'
                     f'（八度差 {r["octave_diff"]} 音单列）')
        lines.append(f'时值级: 音高全同事件中，时值全同 {r["dur_same"]}｜总长错 {r["dur_total_err"]}｜切分错 {r["dur_split_err"]}')
        lines.append(f'结构级: 共有小节 {r["measures_common"]}｜仅真值 {r["measures_only_truth"]}'
                     f'｜仅引擎 {r["measures_only_engine"]}')
        lines.append('符号级: （本卡未测，待真值含标注时启用）')
        lines.append('')
        lines.append(f'三色账: 绿 {r["green"]}｜黄 {r["yellow"]}｜红 {r["red"]}（事件级，合计 {n}）')
    else:
        lines.append('无可比事件（小节无交集或解析为空）')
    if r['detail_red']:
        lines.append('')
        lines.append('红明细（前 15）:')
        for m, kind, tp, ep in r['detail_red'][:15]:
            lines.append(f'  m{m} {kind}: 真值 {tp} → 引擎 {ep}')
    lines.append('')
    lines.append('口径标注: 真值全额核对')
    return '\n'.join(lines)


# ===============================================================

def load(source):
    """'jp:路径' / 'jianpu:路径[:key]' / 'mx:路径' → 事件表"""
    parts = source.split(':', 2)
    kind = parts[0]
    if kind == 'jp':
        return parse_jp_md(parts[1]), parts[1]
    if kind == 'jianpu':
        key = parts[2] if len(parts) > 2 else 'G'
        return parse_jianpu(parts[1], key), parts[1]
    if kind == 'mx':
        return parse_musicxml(parts[1]), parts[1]
    raise ValueError(f'未知来源类型: {kind}')


def main():
    ap = argparse.ArgumentParser(description='统一评价引擎（口径标准 v1.0）')
    ap.add_argument('--truth', help='真值源 jp:路径 或 jianpu:路径:调')
    ap.add_argument('--engine', required=True, help='引擎源 mx:路径')
    ap.add_argument('--inspect', action='store_true', help='只体检不比对')
    ap.add_argument('--json', help='把结果写到 JSON 文件')
    ap.add_argument('--measures', help='只比指定小节范围，如 1-6')
    args = ap.parse_args()

    engine_events, eng_path = load(args.engine)
    if args.inspect or not args.truth:
        by_m = Counter(e.measure for e in engine_events)
        n_notes = sum(len(e.pitches) for e in engine_events if not is_rest(e))
        print(f'体检: {eng_path}')
        print(f'  小节 {len(by_m)} 个；音符 {n_notes} 个；事件 {len(engine_events)} 个')
        print(f'  小节号范围 m{min(by_m)} - m{max(by_m)}' if by_m else '  空谱')
        return

    truth_events, t_path = load(args.truth)
    mr = None
    if args.measures:
        lo, hi = args.measures.split('-')
        mr = (int(lo), int(hi))
    result = evaluate(truth_events, engine_events,
                      label_truth=os.path.basename(t_path),
                      label_engine=os.path.basename(eng_path),
                      measure_range=mr)
    print(report_card(result, title=os.path.basename(eng_path)))
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        print(f'\n（JSON 已写 {args.json}）')


if __name__ == '__main__':
    main()
