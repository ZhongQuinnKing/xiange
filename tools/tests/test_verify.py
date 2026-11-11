#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归用例：verify 三件套的核心纯函数（直方图／小节聚合／tempo 兜底）与 CLI 冒烟。

需核心档（music21、numpy）；缺则如实跳过。跑法：python3 test_verify.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

fails = []


def main():
    try:
        from music21 import stream, note, meter
        import numpy as np
    except ImportError as e:
        print(f'缺核心档（{e}），跳过')
        return 0

    from verify import _pc_hist, _bars_by_measure, _file_bpm

    s = stream.Score()
    p = stream.Part()
    p.append(meter.TimeSignature('4/4'))
    m1 = stream.Measure(number=1)
    m1.append(note.Note('C4', quarterLength=1))
    m1.append(note.Note('E4', quarterLength=1))
    m1.append(note.Note('G4', quarterLength=2))
    p.append(m1)
    m2 = stream.Measure(number=2)
    m2.append(note.Note('D4', quarterLength=4))
    p.append(m2)
    s.append(p)

    h = _pc_hist(s)
    if abs(float(np.dot(h, h) / (np.linalg.norm(h) ** 2)) - 1.0) > 1e-9:
        fails.append('自比直方图余弦不为 1')
    if abs(float(h.sum()) - 1.0) > 1e-9:
        fails.append('直方图未归一')

    bars = _bars_by_measure(s)
    if bars.get(1) != {0, 4, 7}:
        fails.append(f'第 1 小节音高类 {bars.get(1)} != {{0,4,7}}')
    if bars.get(2) != {2}:
        fails.append(f'第 2 小节音高类 {bars.get(2)} != {{2}}')

    if _file_bpm(s) != 120.0:
        fails.append('无 tempo 标记时未按 120 兜底')

    with tempfile.TemporaryDirectory() as td:
        mid = os.path.join(td, 't.mid')
        s.write('midi', fp=mid)
        r = subprocess.run([sys.executable, os.path.join(TOOLS, 'verify.py'), 'metadata', mid],
                           capture_output=True, text=True, timeout=180)
        out = (r.stdout or '') + (r.stderr or '')
        if r.returncode != 0 or '音符元素数' not in out or '文件 tempo' not in out:
            fails.append(f'metadata 冒烟异常 rc={r.returncode}: {out[:150]}')

    if fails:
        print('用例失败：')
        for f in fails:
            print('  -', f)
        return 1
    print('用例通过：直方图／小节聚合／tempo 兜底／metadata 冒烟全过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
