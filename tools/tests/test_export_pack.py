#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归用例：export_pack 的 CLI 契约与失败处置（无渲染档环境也可跑）。

判据：模块可导入（重型依赖均为函数内延迟导入）；--help 正常；源文件不存在时
清晰报错且 rc=1（不裸崩、不产半包）。
跑法：python3 test_export_pack.py
"""
import importlib.util
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)

fails = []


def run(*args):
    r = subprocess.run([sys.executable, os.path.join(TOOLS, 'export_pack.py'), *args],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def main():
    spec = importlib.util.spec_from_file_location('export_pack', os.path.join(TOOLS, 'export_pack.py'))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except ImportError as e:
        fails.append(f'模块导入即拖重型依赖：{e}')

    rc, out = run('--help')
    if rc != 0 or '--title' not in out:
        fails.append(f'--help 异常 rc={rc}')

    with tempfile.TemporaryDirectory() as td:
        rc, out = run('/nonexistent/x.musicxml', '--out', td, '--title', 'T')
        if rc != 1 or '出包失败' not in out:
            fails.append(f'坏源未按预期失败 rc={rc}: {out[-120:]}')

    if fails:
        print('用例失败：')
        for f in fails:
            print('  -', f)
        return 1
    print('用例通过：延迟导入／CLI 契约／坏源 fail-closed 均正确')
    return 0


if __name__ == '__main__':
    sys.exit(main())
