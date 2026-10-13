#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归用例：谱种路由 CLI 契约（无 cv2 环境也可跑）。

断言：①--help rc=0；②无参 rc=2；③缺文件／缺依赖干净报错（rc=2／rc=3，不裸崩）；
④有 cv2 时合成五线谱图判出「五线谱」、空白图如实拒判（unknown）。
跑法：python3 test_spec_route.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
SCRIPT = os.path.join(TOOLS, '工具_谱种路由.py')

try:
    import cv2
    import numpy as np
    HAVE_CV2 = True
except ImportError:
    HAVE_CV2 = False

fails = []


def run(*args):
    r = subprocess.run([sys.executable, SCRIPT, *args],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def main():
    rc, out = run('--help')
    if rc != 0 or '--json' not in out:
        fails.append(f'--help 异常 rc={rc}')

    rc, out = run()
    if rc != 2:
        fails.append(f'无参未 rc=2 rc={rc}: {out[-120:]}')

    with tempfile.TemporaryDirectory() as td:
        rc, out = run(os.path.join(td, 'nope.png'))
        if HAVE_CV2:
            if rc != 2 or '读不到图' not in out or 'Traceback' in out:
                fails.append(f'缺文件未 rc=2 干净报错 rc={rc}: {out[-120:]}')
        else:
            if rc != 3 or '缺依赖' not in out or 'Traceback' in out:
                fails.append(f'缺依赖未 rc=3 干净报错 rc={rc}: {out[-120:]}')

        if HAVE_CV2:
            img = np.full((400, 700), 255, np.uint8)
            for k in range(5):
                y = 100 + k * 20
                cv2.line(img, (60, y), (640, y), 0, 2)
            staff = os.path.join(td, 'staff5.png')
            cv2.imwrite(staff, img)
            rc, out = run(staff)
            if rc != 0 or '五线谱' not in out:
                fails.append(f'合成五线谱未判出 rc={rc}: {out[-160:]}')

            blank = os.path.join(td, 'blank.png')
            cv2.imwrite(blank, np.full((400, 700), 255, np.uint8))
            rc, out = run(blank)
            if rc != 0 or '"unknown"' not in out:
                fails.append(f'空白图未如实拒判 rc={rc}: {out[-160:]}')

    if fails:
        print('用例失败：')
        for f in fails:
            print('  -', f)
        return 1
    print('用例通过：谱种路由 CLI 契约与合成图判读（或 cv2 缺失走 rc=3 干净报错）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
