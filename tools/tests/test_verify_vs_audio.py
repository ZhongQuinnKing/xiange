#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归用例：verify_vs_audio 最小契约（函数件＋CLI；rc 口径 0／2；缺件干净降级）。

断言：①load_machine 合成 MIDI 分桶，移调按 +N 生效；②load_manual 解析页数据
（[?] 与 R 跳过）；③CLI：坏参数 rc=2；缺机器轨／缺手工数据 rc=2 干净报错；
④合成双件同跑 rc=0 出数。
跑法：python3 test_verify_vs_audio.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
from verify_vs_audio import load_machine, load_manual  # noqa: E402

from music21 import note, stream  # noqa: E402

fails = []


def run(*args):
    r = subprocess.run([sys.executable, os.path.join(TOOLS, 'verify_vs_audio.py'), *args],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def main():
    with tempfile.TemporaryDirectory() as td:
        # 1. synthetic MIDI: three notes at offsets 0/4/8, anchor at offset 16 (ruler = last event)
        sc = stream.Stream()
        for off, midi in ((0.0, 60), (4.0, 64), (8.0, 67), (16.0, 72)):
            n = note.Note(midi)
            sc.insert(off, n)
        mid = os.path.join(td, 'm.mid')
        sc.write('midi', fp=mid)

        b0 = load_machine(mid, transpose=0)
        b5 = load_machine(mid, transpose=5)
        if len(b0) != 4 or sorted(b0) != sorted(b5):
            fails.append(f'load_machine 分桶异常：{b0}')
        else:
            if sorted(set().union(*b0.values())) != [0, 4, 7]:
                fails.append(f'load_machine 音高类异常：{b0}')
            if any({(pc + 5) % 12 for pc in b0[k]} != b5[k] for k in b0):
                fails.append('load_machine 移调未按 +5 生效')

        # 2. manual page-data parsing ([?] and R skipped; RH/LH merged into measure sets)
        page = os.path.join(td, 'p1_data.md')
        with open(page, 'w', encoding='utf-8') as fh:
            fh.write('## m1\nRH: [C4,E4,G4]\nLH: [C3]\n## m2\nRH: [D4,F#4,?]\n')
        mb = load_manual([page])
        if mb.get(1) != {0, 4, 7} or mb.get(2) != {2, 6}:
            fails.append(f'load_manual 解析异常：{mb}')

        # 3. CLI contract
        rc, out = run('--bogus')
        if rc != 2 or 'Traceback' in out:
            fails.append(f'坏参数未 rc=2 干净退出 rc={rc}')
        rc, out = run('--machine', os.path.join(td, 'nope.mid'), '--manual', page)
        if rc != 2 or '不存在' not in out or 'Traceback' in out:
            fails.append(f'缺机器轨未 rc=2 干净报错 rc={rc}: {out[-120:]}')
        rc, out = run('--machine', mid, '--manual', os.path.join(td, 'nope.md'))
        if rc != 2 or '不存在' not in out or 'Traceback' in out:
            fails.append(f'缺手工数据未 rc=2 干净报错 rc={rc}: {out[-120:]}')

        # 4. synthetic pair runs together (machine bar1 intersects manual m1)
        rc, out = run('--machine', mid, '--manual', page)
        if rc != 0 or '可比较小节' not in out or 'Traceback' in out:
            fails.append(f'合成样本未跑通 rc={rc}: {out[-160:]}')

    if fails:
        print('用例失败：')
        for f in fails:
            print('  -', f)
        return 1
    print('用例通过：函数件分桶与移调／页数据解析／CLI rc 契约与缺件降级均正确')
    return 0


if __name__ == '__main__':
    sys.exit(main())
