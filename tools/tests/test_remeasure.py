#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归用例：remeasure 的三件纯函数（CREPE 分桶与滤除／手工行解析／页展开）。

只依赖标准库。跑法：python3 test_remeasure.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

from remeasure import machine_by_bar, manual_by_bar, collect_pages

fails = []


def main():
    with tempfile.TemporaryDirectory() as td:
        csvp = os.path.join(td, 'crepe.csv')
        open(csvp, 'w', encoding='utf-8').write(
            't0,dur,beat,midi\n'
            '0.10,0.50,0.0,60\n'   # 第 1 小节 C
            '0.60,0.10,1.0,64\n'   # 时长不足 0.18，应被滤
            '1.00,0.50,4.0,67\n'   # 第 2 小节 G
            '0.05,0.50,8.0,62\n'   # 第 3 小节 D；默认不过滤，t0_min 生效时滤
        )
        bars = machine_by_bar(csvp)
        if bars.get(1) != {0}:
            fails.append(f'machine 第 1 小节 {bars.get(1)} != {{0}}')
        if bars.get(2) != {7}:
            fails.append(f'machine 第 2 小节 {bars.get(2)} != {{7}}')
        if bars.get(3) != {2}:
            fails.append(f'machine 第 3 小节 {bars.get(3)} != {{2}}（默认不应滤）')
        bars2 = machine_by_bar(csvp, t0_min=0.06)
        if 3 in bars2:
            fails.append('t0_min 未滤除早启动音')

    with tempfile.TemporaryDirectory() as td:
        md = os.path.join(td, 'p1.md')
        open(md, 'w', encoding='utf-8').write(
            '# 页 1\n## m1\nRH: [C4,E4]:1.0\nLH: [C3]:1.0\n## m2\nRH: [G4]:0.5\n')
        mb = manual_by_bar([md], hand='RH')
        if mb.get(1) != {0, 4}:
            fails.append(f'manual 第 1 小节 {mb.get(1)} != {{0,4}}')
        if mb.get(2) != {7}:
            fails.append(f'manual 第 2 小节 {mb.get(2)} != {{7}}')
        if set(mb.keys()) != {1, 2}:
            fails.append(f'manual 小节集合异常 {set(mb.keys())}')
        pages = collect_pages([td])
        if [os.path.basename(p) for p in pages] != ['p1.md']:
            fails.append('collect_pages 目录展开异常')

    if fails:
        print('用例失败：')
        for f in fails:
            print('  -', f)
        return 1
    print('用例通过：CREPE 分桶与滤除、手工行解析、页展开全对')
    return 0


if __name__ == '__main__':
    sys.exit(main())
