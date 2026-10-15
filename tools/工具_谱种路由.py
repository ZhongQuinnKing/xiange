#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Score-type router v1 (2026-10-10, system-convergence piece) -- one image in, detect the notation type, route to the matching engine.
# Criteria (rule heuristics, fully explainable):
#   1. horizontal staff-line detection (morphology + grouping): 5-line groups -> staff notation; 6-line groups -> tab
#   2. no staff lines: inspect character blocks: small, many, narrow -> numbered notation; medium square blocks -> block-character notation (guqin/tab, split coarsely by slash density)
#   3. neither -> unknown (honest refusal, no guessing)
# Usage: python3 <this script> <image> [--json out.json]
import argparse
import json
import os

# Late-tolerant visual deps: module imports without them; main fails cleanly with rc=3 (no bare crash)
try:
    import cv2
    import numpy as np
    _DEPS_ERR = None
except ImportError as _e:
    cv2 = np = None
    _DEPS_ERR = _e


def load_gray(path):
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        print(f'读不到图：{path}')
        raise SystemExit(2)
    return img


def detect_hlines(gray):
    """检测水平直线：自适应二值→横向开运算→轮廓→返回水平线段的 (y, x1, x2, 长度)。"""
    h, w = gray.shape
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY_INV, 25, 10)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(30, w // 12), 1))
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kernel)
    cnts, _ = cv2.findContours(horiz, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    lines = []
    for c in cnts:
        x, y, cw, ch = cv2.boundingRect(c)
        if cw >= w * 0.25 and ch <= 6:
            lines.append((y + ch / 2, x, x + cw, cw))
    return sorted(lines)


def longest_equidistant_run(lines, tol=0.35, min_gap=4, max_gap=40):
    """找最长"近等距"水平线串。返回 (串长, 平均间距)。v1.2：替代按 5 条硬找（六线谱会被 5 条子组套中）。"""
    ys = sorted(set(round(l[0]) for l in lines))
    best = (0, 0.0)
    for i in range(len(ys)):
        run = [ys[i]]
        gaps = []
        for j in range(i + 1, len(ys)):
            g = ys[j] - run[-1]
            if min_gap <= g <= max_gap and (not gaps or abs(g - sum(gaps) / len(gaps)) <= tol * (sum(gaps) / len(gaps))):
                gaps.append(g)
                run.append(ys[j])
            elif g > max_gap:
                break
        if len(run) > best[0]:
            best = (len(run), (sum(gaps) / len(gaps)) if gaps else 0.0)
    return best


def char_blocks(gray):
    """字符连通域统计（排除大色块/框线）。"""
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY_INV, 25, 10)
    cnts, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = gray.shape
    blocks = []
    for c in cnts:
        x, y, cw, ch = cv2.boundingRect(c)
        area = cw * ch
        if area < 40 or area > h * w * 0.2:
            continue
        if cw > w * 0.6:      # 横贯=谱线类，不算字
            continue
        blocks.append((cw, ch, area))
    return blocks


def route(path):
    gray = load_gray(path)
    h, w = gray.shape
    lines = detect_hlines(gray)
    run, gap = longest_equidistant_run(lines)
    # Line-count verdict: exactly 6 -> tab; multiple of 5 -> staff (several staves stacked); 5 -> staff; otherwise staff with doubt
    gap6 = gap
    if run == 6:
        g5, g6, gap5 = 0, 1, gap
    elif run >= 5 and run % 5 == 0:
        g5, g6, gap5 = run // 5, 0, gap
    elif run == 5:
        g5, g6, gap5 = 1, 0, gap
    else:
        g5, g6, gap5 = (1 if run >= 5 else 0), 0, gap
    blocks = char_blocks(gray)
    n_blocks = len(blocks)
    if n_blocks:
        med_w = float(np.median([b[0] for b in blocks]))
        med_h = float(np.median([b[1] for b in blocks]))
    else:
        med_w = med_h = 0

    result = {'file': os.path.basename(path), 'size': [w, h],
              'hlines': len(lines), 'staff5_groups': g5, 'staff5_gap': round(gap5, 1),
              'staff6_groups': g6, 'staff6_gap': round(gap6, 1),
              'blocks': n_blocks, 'median_block': [round(med_w, 1), round(med_h, 1)]}

    if g5 >= 2 and gap5 >= 6:
        result.update(spec='五线谱', engine='oemer / SMT（骨架）', why=f'检出 {g5} 组五线谱表（间距 {gap5:.0f}px）')
    elif g6 >= 1 and g6 > g5:
        result.update(spec='六线谱', engine='TabOMR', why=f'检出 {g6} 组六线组')
    elif g5 == 1 and g6 == 0:
        result.update(spec='五线谱', engine='oemer / SMT（骨架）', why='检出 1 组五线谱表')
    elif lines and max(l[3] for l in lines) > w * 0.8 and n_blocks < 40:
        result.update(spec='方格稿/其他表格', engine='待人工', why='长横线多、字块少')
    else:
        # No staff lines: coarse split by ink density (dense scan copy vs sparse print)
        _bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 10)
        ink = float((_bw > 0).mean())
        result['ink'] = round(ink, 4)
        if ink > 0.15:
            result.update(spec='影印密排谱（工尺/古籍类）', engine='SuziOMR（工尺）/ 需目核',
                          why=f'无谱线、墨量比高（{ink:.3f}，影印/密排特征）')
        elif n_blocks >= 60 and 0 < med_w <= w * 0.05 and med_h <= h * 0.06:
            # many small blocks: numbered notation (digits are narrow); block-character notation has larger blocks
            result.update(spec='简谱', engine='OrpheusNet', why=f'无谱线、小字块多（{n_blocks}，中位 {med_w:.0f}x{med_h:.0f}）')
        elif n_blocks >= 20 and med_w > w * 0.03:
            result.update(spec='方块字谱（减字谱/工尺谱）', engine='auto-dapu（古琴）/ SuziOMR（工尺）',
                          why=f'无谱线、中型方块字（{n_blocks}，中位 {med_w:.0f}x{med_h:.0f}）——两类细分待升级')
        else:
            result.update(spec='unknown', engine='拒判', why=f'无谱线、字块少（{n_blocks}）')
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('img')
    ap.add_argument('--json', default=None)
    a = ap.parse_args()
    if _DEPS_ERR is not None:
        print(f'缺依赖：{_DEPS_ERR}（装法：pip install opencv-python numpy）')
        raise SystemExit(3)
    r = route(a.img)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    if a.json:
        json.dump(r, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
