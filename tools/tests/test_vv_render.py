#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归用例：vv_render 交付渲染腿 CLI 契约（无渲染依赖环境也可跑）。

断言：①无参／缺参 rc=2 出用法；②无依赖环境干净报错 rc=3（CI 无 verovio 即走此路）；
③CJK 字体修复只动含中文可渲染文字的元素、其余原样；④有依赖时最小渲染出三件
（svg/png/pdf）且缺文件 rc=2。
跑法：python3 test_vv_render.py
"""
import importlib.util
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
REPO = os.path.dirname(TOOLS)
BENCH = os.path.join(REPO, 'examples', 'bench', '基准01_单旋律八十六分.musicxml')

fails = []


def run(*args):
    r = subprocess.run([sys.executable, os.path.join(TOOLS, 'vv_render.py'), *args],
                       capture_output=True, text=True, timeout=300)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def main():
    # 模块可导入＝依赖缺失不裸崩（延迟容错）
    spec = importlib.util.spec_from_file_location('vv_render', os.path.join(TOOLS, 'vv_render.py'))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except ImportError as e:
        fails.append(f'模块导入即拖渲染依赖：{e}')
        mod = None

    rc, out = run()
    if rc != 2 or '用法' not in out:
        fails.append(f'无参未 rc=2 出用法 rc={rc}: {out[-120:]}')

    rc, out = run('only_one_arg.musicxml')
    if rc != 2:
        fails.append(f'缺参未 rc=2 rc={rc}: {out[-120:]}')

    if mod is not None:
        svg_cjk = '<svg><text><tspan font-family="Times, serif">送别</tspan></text></svg>'
        svg_pure = '<svg><text><tspan font-family="Times, serif">Andante</tspan></text></svg>'
        if 'Hiragino' not in mod.cjk_font_fix(svg_cjk):
            fails.append('CJK 修复未触发（含中文文字元素应换字体）')
        if mod.cjk_font_fix(svg_pure) != svg_pure:
            fails.append('CJK 修复误触（无中文不应改动）')

    with tempfile.TemporaryDirectory() as td:
        base = os.path.join(td, 'out')
        rc, out = run(BENCH, base)
        if rc == 3:
            if '缺渲染依赖' not in out or 'Traceback' in out:
                fails.append(f'缺依赖未干净报错 rc=3 rc={rc}: {out[-120:]}')
        else:
            if rc != 0 or 'OK' not in out:
                fails.append(f'最小渲染失败 rc={rc}: {out[-160:]}')
            else:
                for ext in ('svg', 'png', 'pdf'):
                    fp = f'{base}_p1.{ext}'
                    if not (os.path.exists(fp) and os.path.getsize(fp) > 0):
                        fails.append(f'渲染产物缺件或空：{ext}')
            rc, out = run(os.path.join(td, 'nope.musicxml'), base + '2')
            if rc != 2 or 'Traceback' in out:
                fails.append(f'缺文件未 rc=2 干净报错 rc={rc}: {out[-120:]}')

    if fails:
        print('用例失败：')
        for f in fails:
            print('  -', f)
        return 1
    print('用例通过：vv_render 用法 rc=2／依赖容错／CJK 修复／最小渲染三件（或依赖缺失 rc=3）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
