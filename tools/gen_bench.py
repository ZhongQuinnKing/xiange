#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_bench — 公开基准样例包生成器（2026-10-13 立，批二 Y1 实装）

遵 97 钉一：公开样例一律合成、自造（版权与守清单双重纪律）。
十一首（十首主档＋一首瑕疵校准副件），三组覆盖五线谱各常见语境；
每首是「探针」不是作品：简单、干净、可控为先。

用法（在仓根跑）:
    python3 tools/gen_bench.py            # 生成到 examples/bench/
    python3 tools/gen_bench.py --out 目录
生成物：<out>/<档名>.musicxml × 11 ＋ <out>/清单.json（探针注记＋预期）
"""
import argparse
import json
import os
import sys

import music21 as m21

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_OUT = os.path.join(ROOT, 'examples', 'bench')

C4, D4, E4, F4, G4, A4, B4 = 'C4 D4 E4 F4 G4 A4 B4'.split()
C2, G2, F2 = 'C2 G2 F2'.split()
C3, D3, E3, F3, G3, A3, B3 = 'C3 D3 E3 F3 G3 A3 B3'.split()
C5, D5, E5, F5, G5, A5 = 'C5 D5 E5 F5 G5 A5'.split()


def new_score(title, sig='4/4', key='C'):
    sc = m21.stream.Score()
    sc.metadata = m21.metadata.Metadata()
    sc.metadata.title = title
    md = m21.meter.TimeSignature(sig)
    ks = m21.key.KeySignature(0 if key == 'C' else 0)
    sc._bench_md = md
    return sc, md, ks


def make_part(pid, md, ks, clef='treble'):
    p = m21.stream.Part()
    p.id = pid
    p.append(m21.clef.TrebleClef() if clef == 'treble' else m21.clef.BassClef())
    p.append(md)
    p.append(ks)
    return p


def melody_part(pid, md, ks, measures, clef='treble'):
    """measures: [[('n', pitch, ql) | ('r', ql)], ...]，自动分小节。

    拍号与调号进小节首（music21 不自动写元数据；不入小节则 XML 缺 attributes）。
    """
    p = make_part(pid, md, ks, clef)
    for idx, m in enumerate(measures):
        meas = m21.stream.Measure()
        if idx == 0:
            meas.append(m21.meter.TimeSignature(f'{md.numerator}/{md.denominator}'))
            meas.append(m21.key.KeySignature(ks.sharps))
        for item in m:
            if item[0] == 'r':
                meas.append(m21.note.Rest(quarterLength=item[1]))
            else:
                n = m21.note.Note(item[1], quarterLength=item[2])
                if len(item) > 3 and item[3]:
                    n.tie = m21.tie.Tie(item[3])
                meas.append(n)
        p.append(meas)
    return p


def chords_part(pid, md, ks, measures, clef='treble'):
    """measures: [[('c', [pitches], ql) | ('n', pitch, ql) | ('r', ql)], ...]"""
    p = make_part(pid, md, ks, clef)
    for idx, m in enumerate(measures):
        meas = m21.stream.Measure()
        if idx == 0:
            meas.append(m21.meter.TimeSignature(f'{md.numerator}/{md.denominator}'))
            meas.append(m21.key.KeySignature(ks.sharps))
        for item in m:
            if item[0] == 'r':
                meas.append(m21.note.Rest(quarterLength=item[1]))
            elif item[0] == 'c':
                ch = m21.chord.Chord(item[1], quarterLength=item[2])
                meas.append(ch)
            else:
                meas.append(m21.note.Note(item[1], quarterLength=item[2]))
        p.append(meas)
    return p


def _beam_unit(md):
    """分格单位（四分音符数）：简单拍＝一拍（4/四分音符）；复拍子（6/8 等）＝附点单位 1.5。"""
    beats, bt = int(md.numerator), int(md.denominator)
    if bt == 8 and beats % 3 == 0:
        return 1.5
    return 4.0 / bt


def _beam_by_beat(part, unit):
    """手动按拍赋符杠：拍内「连续可连段」连一链（链首 start／中 continue／尾 stop）。

    判据：同拍格内相邻（位相接）的两个及以上八分及更短音连链；
    不可连音（四分及以上、休止）隔断段——防梁链跨越不可连音（标准排印形态）。
    music21 的 makeBeams 在混合格上会整节罢工（实测），故自赋。
    """
    def beamable(n):
        return (not n.isRest) and n.quarterLength < 1.0

    for m in part.getElementsByClass('Measure'):
        groups = {}
        for n in m.notesAndRests:
            if not beamable(n):
                continue
            # n.offset 即小节内相对位（容器为 Measure；勿再减小节 offset）
            g = int(n.offset // unit)
            groups.setdefault(g, []).append(n)
        for _, notes in groups.items():
            seg = []
            for n in notes:
                if seg and abs(n.offset - (seg[-1].offset + seg[-1].quarterLength)) > 1e-6:
                    _apply_seg(seg)
                    seg = []
                seg.append(n)
            _apply_seg(seg)


def _apply_seg(seg):
    if len(seg) < 2:
        return
    for i, n in enumerate(seg):
        n.beams = m21.beam.Beams()
        if len(seg) == 2:
            n.beams.append('start' if i == 0 else 'stop')
        elif i == 0:
            n.beams.append('start')
        elif i == len(seg) - 1:
            n.beams.append('stop')
        else:
            n.beams.append('continue')


def save(sc, name, outdir, md=None):
    """出谱前按拍赋符杠（防全八分无杠；自赋不走 makeBeams）。

    瑕疵校准副件（名含「瑕疵」）：末二音显式清梁，造「符杠缺失」已知缺陷（N1a 应报）。
    """
    if md is None:
        md = getattr(sc, '_bench_md', None) or m21.meter.TimeSignature('4/4')
    unit = _beam_unit(md)
    for p in sc.parts:
        _beam_by_beat(p, unit)
    if '瑕疵' in name:
        for p in sc.parts:
            last_m = list(p.getElementsByClass('Measure'))[-1]
            tail = [n for n in last_m.notesAndRests if not n.isRest][-2:]
            for n in tail:
                n.beams = m21.beam.Beams()
    path = os.path.join(outdir, name + '.musicxml')
    sc.write('musicxml', fp=path)
    return path


# ── 十一首 ──────────────────────────────────────────────────

def p01():
    """单旋律小曲：八分十六分组合，探符杠分组与符干方向。"""
    sc, md, ks = new_score('基准01_单旋律八十六分')
    ms = [
        [('n', C4, 1.0), ('n', D4, 0.5), ('n', E4, 0.5), ('n', F4, 0.25), ('n', G4, 0.25),
         ('n', A4, 0.5), ('n', B4, 0.5), ('n', C5, 0.5)],
        [('n', G4, 0.5), ('n', E4, 0.5), ('n', C4, 1.0), ('n', F4, 0.5), ('n', A4, 0.5),
         ('n', G4, 1.0)],
        [('n', E4, 0.25), ('n', F4, 0.25), ('n', G4, 0.25), ('n', A4, 0.25),
         ('n', B4, 0.5), ('n', C5, 0.5), ('n', D5, 0.5), ('n', B4, 0.5), ('n', G4, 1.0)],
        [('n', C5, 2.0), ('n', G4, 1.0), ('n', C4, 1.0)],
    ]
    sc.append(melody_part('P1', md, ks, ms))
    return sc


def p02():
    """旋律加伴奏（两手）：探谱表分配与声部归属。"""
    sc, md, ks = new_score('基准02_旋律加伴奏两手')
    rh = [
        [('n', E4, 1.0), ('n', G4, 1.0), ('n', C5, 2.0)],
        [('n', D5, 1.0), ('n', B4, 1.0), ('n', C5, 2.0)],
    ]
    lh = [
        [('c', [C3, E3, G3], 4.0)],
        [('c', [G3, B3, D4], 4.0)],
    ]
    p1 = melody_part('P1', md, ks, rh, 'treble')
    p2 = chords_part('P2', md, ks, lh, 'bass')
    sc.insert(0, p1)
    sc.insert(0, p2)
    return sc


def p03():
    """复拍子小曲（6/8）：探复拍子按附点单位分组。每小节 3.0 QL。"""
    sc, md, ks = new_score('基准03_复拍子六八', sig='6/8')
    ms = [
        [('n', G4, 1.5), ('n', A4, 0.5), ('n', B4, 0.5), ('n', C5, 0.5)],
        [('n', E5, 1.5), ('n', D5, 0.5), ('n', C5, 1.0)],
        [('n', A4, 0.5), ('n', B4, 0.5), ('n', C5, 0.5), ('n', B4, 0.5), ('n', A4, 1.0)],
        [('n', G4, 1.5), ('n', C5, 1.5)],
    ]
    sc.append(melody_part('P1', md, ks, ms))
    return sc


def p04():
    """合唱缩谱（四声部）：探多声部密度与归属核对。"""
    sc, md, ks = new_score('基准04_合唱缩谱四声部')
    sop = [[('n', E5, 4.0)], [('n', G5, 4.0)]]
    alto = [[('n', C5, 4.0)], [('n', D5, 4.0)]]
    ten = [[('n', G4, 4.0)], [('n', B4, 4.0)]]
    bass = [[('n', C4, 4.0)], [('n', G3, 4.0)]]
    for i, ms in enumerate([sop, alto, ten, bass], start=1):
        sc.append(melody_part(f'P{i}', md, ks, ms, 'treble' if i < 4 else 'bass'))
    return sc


def p05():
    """简谱型单声部（含附点、切分）：探减时线、附点、空拍（用五线记谱合成等价物）。"""
    sc, md, ks = new_score('基准05_附点切分单声部')
    ms = [
        [('n', C4, 0.75), ('n', D4, 0.125), ('n', E4, 0.125), ('n', F4, 1.0), ('n', F4, 0.75),
         ('n', E4, 0.125), ('n', D4, 0.125), ('n', C4, 1.0)],
        [('r', 0.5), ('n', G4, 0.5), ('n', G4, 1.0), ('n', A4, 0.75), ('n', G4, 0.125),
         ('n', F4, 0.125), ('n', E4, 1.0)],
    ]
    sc.append(melody_part('P1', md, ks, ms))
    return sc


def p06():
    """带变化音单声部：探变音记号呈现。"""
    sc, md, ks = new_score('基准06_变化音单声部')
    ms = [
        [('n', E4, 1.0), ('n', 'F#4', 1.0), ('n', G4, 1.0), ('n', 'B-4', 1.0)],
        [('n', A4, 1.0), ('n', 'G#4', 0.5), ('n', A4, 0.5), ('n', 'F#4', 1.0), ('n', E4, 1.0)],
    ]
    sc.append(melody_part('P1', md, ks, ms))
    return sc


def p07():
    """钢琴两手小品：探左右手分离与跨声部串配。"""
    sc, md, ks = new_score('基准07_钢琴两手小品')
    rh = [
        [('n', E4, 0.5), ('n', G4, 0.5), ('n', C5, 1.0), ('n', B4, 0.5), ('n', G4, 0.5), ('n', E4, 1.0)],
        [('n', F4, 0.5), ('n', A4, 0.5), ('n', C5, 2.0), ('n', B4, 1.0)],
    ]
    lh = [
        [('c', [C3, G3], 2.0), ('c', [E3, G3], 2.0)],
        [('c', [F3, C4], 2.0), ('c', [G3, B3], 2.0)],
    ]
    p1 = melody_part('P1', md, ks, rh, 'treble')
    p2 = chords_part('P2', md, ks, lh, 'bass')
    sc.insert(0, p1)
    sc.insert(0, p2)
    return sc


def p08():
    """钢琴两手带切分织体：探时值级（总长错与切分错分开计）。"""
    sc, md, ks = new_score('基准08_钢琴切分织体')
    rh = [
        [('n', E4, 0.5), ('n', G4, 0.5), ('n', C5, 1.5), ('n', B4, 0.5), ('n', C5, 1.0)],
        [('n', D5, 1.5), ('n', C5, 0.5), ('n', B4, 1.5), ('n', G4, 0.5)],
    ]
    lh = [
        [('c', [C3, G3], 1.0), ('c', [G2, D3], 1.0), ('c', [C3, E3], 2.0)],
        [('c', [F2, C3], 1.0), ('c', [G2, D3], 1.0), ('c', [C3, G3], 2.0)],
    ]
    p1 = melody_part('P1', md, ks, rh, 'treble')
    p2 = chords_part('P2', md, ks, lh, 'bass')
    sc.insert(0, p1)
    sc.insert(0, p2)
    return sc


def p09():
    """三重奏缩谱（三行）：探行数与谱表分配。"""
    sc, md, ks = new_score('基准09_三重奏缩谱三行')
    va = [[('n', E4, 2.0), ('n', F4, 2.0)], [('n', G4, 4.0)]]
    vc = [[('n', C3, 2.0), ('n', D3, 2.0)], [('n', E3, 4.0)]]
    vn = [[('n', G4, 2.0), ('n', A4, 2.0)], [('n', C5, 4.0)]]
    for pid, ms, clef in [('P1', vn, 'treble'), ('P2', va, 'treble'), ('P3', vc, 'bass')]:
        sc.append(melody_part(pid, md, ks, ms, clef))
    return sc


def p10():
    """弦乐四重奏缩谱：探四声部归属与符干约定。"""
    sc, md, ks = new_score('基准10_四重奏缩谱')
    v1 = [[('n', G4, 1.0), ('n', A4, 1.0), ('n', B4, 2.0)], [('n', C5, 4.0)]]
    v2 = [[('n', E4, 1.0), ('n', F4, 1.0), ('n', G4, 2.0)], [('n', E4, 4.0)]]
    va = [[('n', C4, 1.0), ('n', D4, 1.0), ('n', E4, 2.0)], [('n', G4, 4.0)]]
    vc = [[('n', C3, 1.0), ('n', D3, 1.0), ('n', E3, 2.0)], [('n', C3, 4.0)]]
    for pid, ms, clef in [('P1', v1, 'treble'), ('P2', v2, 'treble'),
                          ('P3', va, 'treble'), ('P4', vc, 'bass')]:
        sc.append(melody_part(pid, md, ks, ms, clef))
    return sc


def p11():
    """瑕疵校准副件：末小节故意多写一拍（八分未连符杠＋时值越界），
    预期记谱／对账两关各出一处，供双向校准（不漏报）。"""
    sc, md, ks = new_score('基准11_瑕疵校准副件')
    ms = [
        [('n', C4, 0.5), ('n', D4, 0.5), ('n', E4, 0.5), ('n', F4, 0.5),
         ('n', G4, 1.0), ('n', A4, 1.0)],
        [('n', B4, 1.0), ('n', A4, 1.0), ('n', G4, 1.0), ('n', C5, 1.0),
         ('n', B4, 0.5), ('n', C5, 0.5), ('n', D5, 1.0), ('n', E5, 1.0), ('n', F5, 0.25), ('n', G5, 0.25)],
    ]
    sc.append(melody_part('P1', md, ks, ms))
    return sc


PIECES = [
    ('基准01_单旋律八十六分', p01, '探符杠分组、符干方向'),
    ('基准02_旋律加伴奏两手', p02, '探谱表分配、声部归属'),
    ('基准03_复拍子六八', p03, '探复拍子按附点单位分组'),
    ('基准04_合唱缩谱四声部', p04, '探多声部密度与归属核对'),
    ('基准05_附点切分单声部', p05, '探减时线、附点、空拍'),
    ('基准06_变化音单声部', p06, '探八度点与调号呈现'),
    ('基准07_钢琴两手小品', p07, '探左右手分离与跨声部串配'),
    ('基准08_钢琴切分织体', p08, '探时值级（总长错与切分错分开计）'),
    ('基准09_三重奏缩谱三行', p09, '探行数与谱表分配'),
    ('基准10_四重奏缩谱', p10, '探四声部归属与符干约定'),
    ('基准11_瑕疵校准副件', p11, '校准不漏报：末小节净多一拍（预期报错）'),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=DEFAULT_OUT)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    manifest = []
    for name, fn, probe in PIECES:
        sc = fn()
        path = save(sc, name, args.out)
        manifest.append({'file': os.path.basename(path), 'probe': probe,
                         'kind': 'defect' if name.endswith('瑕疵校准副件') else 'clean'})
        print(f'生成 {os.path.basename(path)}')
    with open(os.path.join(args.out, '清单.json'), 'w', encoding='utf-8') as fh:
        json.dump({'version': 1, 'note': '九九钉一：样例全部合成自造；本包验流程可复现，不承诺准确率数字。',
                   'pieces': manifest}, fh, ensure_ascii=False, indent=1)
    print(f'共 {len(manifest)} 首 → {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
