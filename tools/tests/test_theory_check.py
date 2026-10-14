#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
theory_check 自校验 — 构造病例谱，验证每条规则的真阳性与假阳性

病例（人工构造，症状已知）：
  干净例   C-G-Am-F 四部写法        → 不许有任何严重项
  平行五度 m1-2：两外声部同向 C-G / D-A → E3 必须报
  声部交叉 m3  ：高声部掉到低声部下方   → E1 必须报
  跨度过大   m4  ：右单手同时按 15 度     → E4 必须报
  密度骤降 m5  ：持续二分和弦后骤降为单音 → E5 必须报
  密度反例 m6-7：只少一音／短和弦接单音 → E5 不许报
  E1 豁免五例  ：声部／小节参数放行；豁免名未匹配照报；区间只罩指定段与罩全段

用法: python3 test_theory_check.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import theory_check as tc
from theory_check import build_report

from music21 import stream, note, chord, meter


def make_score(cases):
    """cases: {measure_no: [('RH'|'LH', [midi...], quarterLength), ...]}"""
    sc = stream.Score()
    parts = []
    for part_name in ('RH', 'LH'):
        p = stream.Part()
        p.partName = part_name
        p.append(meter.TimeSignature('4/4'))
        for mno in sorted(cases):
            m = stream.Measure(number=mno)
            for hand, midis, ql in cases[mno]:
                if hand != part_name:
                    continue
                if len(midis) == 1:
                    n = note.Note(midis[0])
                else:
                    n = chord.Chord(midis)
                n.quarterLength = ql
                m.append(n)
            p.append(m)
        parts.append(p)
    for p in reversed(parts):
        sc.insert(0, p)
    return sc


def run_case(name, cases, must, must_not):
    sc = make_score(cases)
    fd, tmp = tempfile.mkstemp(suffix='.musicxml')
    os.close(fd)
    sc.write('musicxml', fp=tmp)
    res = build_report(tmp)
    os.unlink(tmp)
    codes = [f[1] for f in res[1]]
    ok = all(c in codes for c in must) and all(c not in codes for c in must_not)
    mark = '✓' if ok else '✗'
    print(f'{mark} {name}: 症状={codes}｜须有={must} 须无={must_not}')
    return ok


def run_case_params(name, cases, must, must_not, e1_exempt=None, e1_ranges=None):
    """带 E1 豁免参数的病例（设／复位模块级参数，试后必还原）"""
    tc.E1_EXEMPT = list(e1_exempt or [])
    tc.E1_RANGES = [tuple(r) for r in (e1_ranges or [])]
    try:
        return run_case(name, cases, must, must_not)
    finally:
        tc.E1_EXEMPT, tc.E1_RANGES = [], []


def main():
    all_ok = True

    # 1 干净例：C 大三和弦上下分布，无并行五八度无交叉
    clean = {
        1: [('RH', [67, 72], 4.0), ('LH', [48, 55, 60], 4.0)],
        2: [('RH', [65, 69], 4.0), ('LH', [45, 53, 57], 4.0)],
    }
    all_ok &= run_case('干净例无严重项', clean, must=[], must_not=['E1', 'E3', 'E4'])

    # 2 平行五度：RH 62→64，LH 55→57（同向，间隔恒为 7）
    p5 = {
        1: [('RH', [62], 2.0), ('LH', [55], 2.0)],
        2: [('RH', [64], 2.0), ('LH', [57], 2.0)],
    }
    all_ok &= run_case('平行五度被捉', p5, must=['E3'], must_not=['E4'])

    # 3 声部交叉：RH 掉到 50，LH 在 60
    cross = {
        1: [('RH', [50], 4.0), ('LH', [60], 4.0)],
    }
    all_ok &= run_case('声部交叉被捉', cross, must=['E1'], must_not=['E3', 'E4'])

    # 4 跨度过大：RH 同拍 60 与 78（18 半音，默认上限 20 内不报），60 与 82（22 半音）报
    # [本地适配 2026-10-11] 默认跨度上限 16 改 20 后本例同步按 20 标定（测试腐化修复）
    span = {
        1: [('RH', [60, 78], 2.0), ('LH', [40], 4.0)],
        2: [('RH', [60, 82], 2.0), ('LH', [40], 4.0)],
    }
    all_ok &= run_case('跨度过大被捉（大十度不误报）', span, must=['E4'], must_not=['E1'])

    # 5 声部密度骤降：LH 持续二分和弦 [48,55,59] 后骤降为单音 57 → E5 必须报
    dens = {
        1: [('LH', [48, 55, 59], 2.0), ('LH', [57], 2.0), ('RH', [67], 4.0)],
    }
    all_ok &= run_case('声部密度骤降被捉', dens, must=['E5'], must_not=['E1', 'E3', 'E4'])

    # 6 密度规则不误报：①持续和弦后只少一音（4→3）不报；②短和弦（1 拍）后接单音不报
    dens_ok = {
        1: [('LH', [48, 52, 55, 59], 2.0), ('LH', [48, 52, 57], 2.0)],
        2: [('LH', [48, 55, 59], 1.0), ('LH', [57], 3.0)],
    }
    all_ok &= run_case('密度规则不误报（少一音／短和弦）', dens_ok, must=[], must_not=['E5'])

    # 7-10 E1 豁免参数（供设计性交叉放行；基线报警见病例 3）
    all_ok &= run_case_params('E1 豁免（声部参数）放行', cross, must=[], must_not=['E1'],
                              e1_exempt=['RH'])
    all_ok &= run_case_params('E1 豁免（小节参数）放行', cross, must=[], must_not=['E1'],
                              e1_ranges=[(1, 1)])
    all_ok &= run_case_params('豁免名未匹配仍报（不许静默放行）', cross, must=['E1'],
                              must_not=[], e1_exempt=['NoSuchPart'])
    cross2 = {
        1: [('RH', [50], 4.0), ('LH', [60], 4.0)],
        2: [('RH', [50], 4.0), ('LH', [60], 4.0)],
    }
    all_ok &= run_case_params('小节参数只罩指定段（区外照报）', cross2, must=['E1'],
                              must_not=[], e1_ranges=[(2, 2)])
    all_ok &= run_case_params('小节参数罩全段（净）', cross2, must=[], must_not=['E1'],
                              e1_ranges=[(1, 2)])

    # CLI 契约：缺文件须干净 fail-closed（rc=2、无 Traceback）
    import subprocess
    r = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      '..', 'theory_check.py'), '/nonexistent_probe.musicxml'],
        capture_output=True, text=True)
    if r.returncode != 2 or 'Traceback' in r.stderr:
        all_ok = False
        print(f'✗ 缺文件未干净 fail-closed（rc={r.returncode}）')

    # CLI 契约：--e1-range 格式错须干净 fail-closed（rc=2、无 Traceback）
    r2 = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      '..', 'theory_check.py'),
         '--e1-range', '9x', '/nonexistent_probe.musicxml'],
        capture_output=True, text=True)
    if r2.returncode != 2 or 'Traceback' in r2.stderr:
        all_ok = False
        print(f'✗ --e1-range 格式错未干净 fail-closed（rc={r2.returncode}）')

    print()
    if all_ok:
        print('✓✓ 全部病例过（含 E1 豁免五例）— 乐理错检器判据正确')
    else:
        print('✗✗ 有病例不过，修到全过为止')
        sys.exit(1)


if __name__ == '__main__':
    main()
