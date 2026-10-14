#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从"翻页式"谱视频中提取谱页图（技能包 tools）

背景：B站等平台的钢琴谱视频常为"每约 9 秒翻一页"结构。本工具用 ffmpeg 抽帧，
帧差自动检出翻页点，取每页稳定中点帧导出为图。

依赖: ffmpeg（外部命令）、pip install opencv-python numpy
用法:
  python bili_extract.py <视频文件> -o <输出目录> [--step 1.0] [--diff 8]
    --step  采样间隔（秒，默认 1）
    --diff  翻页判定帧差阈值（默认 8；漏检就调小，误报就调大）
    --crop-top / --crop-bottom  裁掉顶部/底部比例（默认 0 / 0.26，去底部键盘带）
输出: 输出目录/page_XX.png 与 _overview.jpg
退出码: 0=成；2=用法／视频不存在；3=缺依赖（opencv-python／numpy／ffmpeg）

备注：不直接用 cv2.VideoCapture 读视频——对部分 B站 mp4 编码会失败；
ffmpeg 抽帧最稳（实测）。
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile

try:
    import cv2
    import numpy as np
    _HAVE_CV = True
except ImportError:  # 缺件走干净降级：--help 仍可用，跑时 rc=3
    _HAVE_CV = False


def main():
    ap = argparse.ArgumentParser(description='谱视频提页')
    ap.add_argument('video')
    ap.add_argument('-o', '--outdir', default='bili_pages')
    ap.add_argument('--step', type=float, default=1.0, help='采样间隔（秒）')
    ap.add_argument('--diff', type=float, default=8.0, help='翻页帧差阈值')
    ap.add_argument('--crop-top', type=float, default=0.0)
    ap.add_argument('--crop-bottom', type=float, default=0.26)
    args = ap.parse_args()

    if not _HAVE_CV:
        sys.stderr.write('缺依赖：需要 opencv-python 与 numpy（pip install opencv-python numpy）\n')
        sys.exit(3)
    if not os.path.exists(args.video):
        sys.stderr.write(f'视频不存在：{args.video}\n')
        sys.exit(2)
    if not shutil.which('ffmpeg'):
        sys.stderr.write('缺依赖：需要 ffmpeg（brew install ffmpeg）\n')
        sys.exit(3)

    tmp = tempfile.mkdtemp(prefix='score_frames_')
    try:
        cmd = ['ffmpeg', '-y', '-i', args.video,
               '-vf', f'fps={1.0 / args.step}', '-q:v', '2',
               os.path.join(tmp, 'f_%04d.jpg')]
        r = subprocess.run(cmd, capture_output=True, text=True)
        files = sorted(glob.glob(os.path.join(tmp, 'f_*.jpg')))
        if not files:
            raise SystemExit(f'ffmpeg 没抽出帧：{r.stderr[-400:]}')
        frames = []
        for f in files:
            im = cv2.imread(f)
            h = im.shape[0]
            t = int(h * args.crop_top)
            b = int(h * (1 - args.crop_bottom))
            frames.append(im[t:b])
        print(f'采样帧数: {len(frames)}')

        cuts = [0]
        prev = None
        for i, f in enumerate(frames):
            g = cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (240, 339))
            if prev is not None:
                d = np.abs(g.astype(int) - prev.astype(int)).mean()
                if d > args.diff:
                    cuts.append(i)
            prev = g
        cuts.append(len(frames))
        reps = [frames[(a + b) // 2] for a, b in zip(cuts[:-1], cuts[1:])]
        print(f'检测到 {len(reps)} 页')

        os.makedirs(args.outdir, exist_ok=True)
        for i, im in enumerate(reps, 1):
            cv2.imwrite(os.path.join(args.outdir, f'page_{i:02d}.png'), im)
        w = reps[0].shape[1]
        canvas = np.full((sum(r.shape[0] for r in reps) + 8 * len(reps), w, 3), 255, np.uint8)
        y = 0
        for r_ in reps:
            canvas[y:y + r_.shape[0], :w] = r_
            y += r_.shape[0] + 8
        cv2.imwrite(os.path.join(args.outdir, '_overview.jpg'), canvas,
                    [cv2.IMWRITE_JPEG_QUALITY, 85])
        print(f'完成: {args.outdir}/page_01..{len(reps):02d}.png + _overview.jpg')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
