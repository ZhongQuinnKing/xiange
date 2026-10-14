#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归用例：bili_extract 最小契约（rc 口径 0／2／3；缺件干净降级，不许裸崩）。

断言：①--help 可用（缺 cv2 也不崩在 import）；②坏参数 rc=2；③缺视频：有 cv2 rc=2／
无 cv2 rc=3（缺依赖），均无 Traceback；④有 cv2 无 ffmpeg：rc=3 干净报缺；
⑤依赖齐备：合成小视频跑通 rc=0 出页图。
跑法：python3 test_bili_extract.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
SCRIPT = os.path.join(TOOLS, 'bili_extract.py')

try:
    import cv2  # noqa: F401
    HAVE_CV2 = True
except ImportError:
    HAVE_CV2 = False
HAVE_FFMPEG = shutil.which('ffmpeg') is not None

fails = []


def run(*args):
    r = subprocess.run([sys.executable, SCRIPT, *args],
                       capture_output=True, text=True, timeout=180)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def main():
    rc, out = run('--help')
    if rc != 0 or '--step' not in out or 'Traceback' in out:
        fails.append(f'--help 异常 rc={rc}: {out[-120:]}')

    rc, out = run('--bogus')
    if rc != 2 or 'Traceback' in out:
        fails.append(f'坏参数未 rc=2 干净退出 rc={rc}')

    with tempfile.TemporaryDirectory() as td:
        rc, out = run(os.path.join(td, 'nope.mp4'))
        if HAVE_CV2:
            if rc != 2 or '不存在' not in out or 'Traceback' in out:
                fails.append(f'缺视频未 rc=2 干净报错 rc={rc}: {out[-120:]}')
        else:
            if rc != 3 or '缺依赖' not in out or 'Traceback' in out:
                fails.append(f'缺依赖未 rc=3 干净报错 rc={rc}: {out[-120:]}')

        if HAVE_CV2 and not HAVE_FFMPEG:
            dummy = os.path.join(td, 'd.mp4')
            with open(dummy, 'wb') as fh:
                fh.write(b'\x00' * 16)
            rc, out = run(dummy, '-o', os.path.join(td, 'out'))
            if rc != 3 or 'ffmpeg' not in out or 'Traceback' in out:
                fails.append(f'缺 ffmpeg 未 rc=3 干净报错 rc={rc}: {out[-120:]}')

        if HAVE_CV2 and HAVE_FFMPEG:
            src = os.path.join(td, 'src.mp4')
            g = subprocess.run(['ffmpeg', '-y', '-f', 'lavfi', '-i',
                                'testsrc=duration=2:size=64x64:rate=2',
                                '-pix_fmt', 'yuv420p', src],
                               capture_output=True, text=True)
            if g.returncode == 0:
                outdir = os.path.join(td, 'pages')
                rc, out = run(src, '-o', outdir, '--step', '1')
                if rc != 0 or not os.path.exists(os.path.join(outdir, 'page_01.png')) \
                        or '检测到' not in out or 'Traceback' in out:
                    fails.append(f'合成小视频未跑通 rc={rc}: {out[-160:]}')
            else:
                print('注：ffmpeg 合成视频失败，跳过跑通面（环境不支持）')

    if fails:
        print('用例失败：')
        for f in fails:
            print('  -', f)
        return 1
    print('用例通过：CLI 契约与缺件降级（cv2%s／ffmpeg%s）'
          % ('有' if HAVE_CV2 else '无', '有' if HAVE_FFMPEG else '无'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
