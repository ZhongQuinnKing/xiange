#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归用例：deliver_dolce 的依赖守卫与命令行契约，批二 X4 补。

浏览器档在 CI 不装，本用例覆盖两面：无依赖时 fail-closed（清晰报缺、非零退出，
不许裸崩在 import）；有依赖时 CLI 契约稳定（互斥组与必填项）。
跑法：python3 test_deliver_dolce.py
"""
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)

fails = []


def run(*args):
    r = subprocess.run([sys.executable, os.path.join(TOOLS, 'deliver_dolce.py'), *args],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def main():
    spec = importlib.util.spec_from_file_location('deliver_dolce', os.path.join(TOOLS, 'deliver_dolce.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    deps = mod.sync_playwright is not None and mod.cairosvg is not None

    if deps:
        rc, out = run('--help')
        if rc != 0 or '--xml' not in out or '--batch' not in out:
            fails.append(f'--help 异常 rc={rc}')
        rc, _ = run()
        if rc != 2:
            fails.append(f'无参应 argparse 退出 2，实得 {rc}')
        rc, _ = run('--xml', 'a.xml', '--batch', 'd', '--out', 'o')
        if rc != 2:
            fails.append(f'--xml 与 --batch 互斥未生效，实得 {rc}')
        rc, _ = run('--xml', 'a.xml')
        if rc != 2:
            fails.append(f'缺 --out 未报错，实得 {rc}')
    else:
        rc, out = run('--xml', 'a.xml', '--out', 'o')
        if rc != 1 or '缺依赖' not in out:
            fails.append(f'无依赖未 fail-closed：rc={rc} out={out[:150]}')

    if fails:
        print('用例失败：')
        for f in fails:
            print('  -', f)
        return 1
    print('用例通过（依赖%s分支）：%s' % ('在位' if deps else '缺省', 'CLI 契约稳定' if deps else 'fail-closed 生效'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
