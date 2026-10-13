#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归用例：bekern_fix 的 spine 归一化（分裂/合并感知），批二 X4 补。

归一化是纯函数，本用例直测六点：头尾齐全、两列直通、*^ 分裂取槽、
*v 合并、同槽取长记号、槽位不足补「.」顶齐。
跑法：python3 test_bekern_fix.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

from bekern_fix import normalize, pick

fails = []


def main():
    # ① 头尾与两列直通
    out = normalize('**kern\n4c\t4e\n*-\t*-').split('\n')
    if out[0] != '**kern\t**kern':
        fails.append('缺头部表头')
    if out[-1] != '*-\t*-':
        fails.append('缺尾部终止')
    if '4c\t4e' not in out:
        fails.append('两列直通异常')

    # ② *^ 分裂：第 2 槽裂成两列后，同槽多列时取长记号归并回槽
    raw = '**kern\n.\t*^\n4c\t4d\t4e\n*-\t*-'
    out = normalize(raw).split('\n')
    if '*\t*' not in out:
        fails.append('分裂行未见槽位记号')
    if '4c\t4d' not in out:
        fails.append('分裂后取槽异常')

    # ③ *v 合并：裂开的两列并回一槽
    raw = '**kern\n.\t*^\n4c\t4d\t4e\n.\t*v\t*v\n4f\t4g\n*-\t*-'
    out = normalize(raw).split('\n')
    if '4f\t4g' not in out:
        fails.append('合并后取槽异常')

    # ④ 取长记号
    if pick(['', '.', '4a', '16bb']) != '16bb':
        fails.append('pick 未取最长记号')
    if pick(['', '.']) != '.':
        fails.append('pick 全空未回退「.」')

    # ⑤ 槽位不足补「.」顶齐
    out = normalize('**kern\n4c\n*-\t*-').split('\n')
    if '4c\t.' not in out:
        fails.append('单列输入未补「.」顶齐')

    if fails:
        print('用例失败：')
        for f in fails:
            print('  -', f)
        return 1
    print('用例通过：归一化六查（头尾／直通／分裂／合并／取长／补点）全过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
