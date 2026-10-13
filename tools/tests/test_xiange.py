#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归用例：xiange 统一壳（CLI 契约）。

验四事：①未知子命令 rc=2；②check 缺文件 rc=2 且不裸崩；③doctor 可跑（rc 0 或 3）
且 --json 为合法 JSON；④selfcheck --list 正确列出套件清单。

跑法：python3 test_xiange.py
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

fails = []


def run(*args):
    r = subprocess.run([sys.executable, os.path.join(TOOLS, 'xiange.py'), *args],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def main():
    rc, out = run('no_such_cmd')
    if rc != 2:
        fails.append(f'未知子命令 rc={rc}（期望 2）')

    rc, out = run('check', '/nonexistent_probe.musicxml')
    if rc != 2 or 'Traceback' in out:
        fails.append(f'check 缺文件 rc={rc} 或裸崩（期望 2 且干净）')

    rc, out = run('doctor', '--json')
    if rc not in (0, 3):
        fails.append(f'doctor rc={rc}（期望 0 或 3）')
    else:
        try:
            d = json.loads(out[out.index('{'):])
            if 'checks' not in d or 'core_ok' not in d:
                fails.append('doctor --json 结构缺 checks／core_ok')
        except (ValueError, json.JSONDecodeError):
            fails.append('doctor --json 非合法 JSON')

    rc, out = run('selfcheck', '--list')
    if rc != 0 or 'test_xiange.py' not in out:
        fails.append('selfcheck --list 未列出套件（含自身）')

    if fails:
        print('用例失败：')
        for f in fails:
            print('  -', f)
        return 1
    print('用例通过：xiange 壳契约（未知命令／缺文件／doctor／selfcheck 列表）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
