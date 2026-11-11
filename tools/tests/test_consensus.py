#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归用例：consensus 共识融合（pc／notes／seq 三模式契约）。

fixture 自足：music21 现场构造两小节乐谱写 MusicXML；bekern 文本内嵌
（内容在前的常规 kern 排法，含小写音名——2026-10-13 修的丢小写音回归位）。
断言：三模式 rc=0 且判读正确；B 侧空不裸崩；缺文件 rc=2 干净报错。
跑法：python3 test_consensus.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)

KRN = '**kern\n*M4/4\n4c\n4e\n2g\n=1\n4f\n4a\n2cc\n=2\n*-\n'

fails = []


def run(*args):
    r = subprocess.run([sys.executable, os.path.join(TOOLS, 'consensus.py'), *args],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def make_musicxml(td):
    from music21 import stream, note, meter
    sc = stream.Score()
    p = stream.Part()
    m1 = stream.Measure(number=1)
    m1.append(meter.TimeSignature('4/4'))
    for nm in ('C4', 'E4'):
        m1.append(note.Note(nm, quarterLength=1.0))
    m1.append(note.Note('G4', quarterLength=2.0))
    m2 = stream.Measure(number=2)
    for nm in ('F4', 'A4'):
        m2.append(note.Note(nm, quarterLength=1.0))
    m2.append(note.Note('C5', quarterLength=2.0))
    p.append([m1, m2])
    sc.append(p)
    fp = os.path.join(td, 'mini.musicxml')
    sc.write('musicxml', fp=fp)
    return fp


def main():
    with tempfile.TemporaryDirectory() as td:
        mx = make_musicxml(td)
        krn = os.path.join(td, 'mini.krn')
        with open(krn, 'w', encoding='utf-8') as f:
            f.write(KRN)
        empty = os.path.join(td, 'empty.krn')
        with open(empty, 'w', encoding='utf-8') as f:
            f.write('**kern\n*M4/4\n=1\n*-\n')

        rc, out = run('pc', mx, krn)
        if rc != 0 or '共识 [C E G]' not in out or '待裁音类 0' not in out:
            fails.append(f'pc 模式判读不对 rc={rc}: {out[-160:]}')

        rc, out = run('seq', mx, krn)
        if rc != 0 or '对齐位 6' not in out or '同音类 6' not in out:
            fails.append(f'seq 模式判读不对 rc={rc}: {out[-160:]}')

        rc, out = run('notes', mx, krn)
        if rc != 0 or '骨架音符事件：6 个' not in out or '100%' not in out:
            fails.append(f'notes 模式判读不对 rc={rc}: {out[-160:]}')

        rc, out = run('notes', mx, empty)
        if rc != 0 or '无音符' not in out or 'Traceback' in out:
            fails.append(f'B 侧空未按预期给出说明 rc={rc}: {out[-160:]}')

        rc, out = run('pc', os.path.join(td, 'nope.musicxml'), krn)
        if rc != 2 or 'Traceback' in out or '不存在' not in out:
            fails.append(f'缺文件未 rc=2 干净报错 rc={rc}: {out[-160:]}')

    if fails:
        print('用例失败：')
        for f in fails:
            print('  -', f)
        return 1
    print('用例通过：consensus 三模式判读／B 侧空说明／缺文件 rc=2')
    return 0


if __name__ == '__main__':
    sys.exit(main())
