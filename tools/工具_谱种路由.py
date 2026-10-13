#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 谱种路由 v1（2026-10-10，体系汇合件）——一张图进来判谱种，路由到对应引擎。
# 判据（规则启发，全过程可解释）：
#   ① 水平谱线检测（形态学横线+分组）：五线组→五线谱；六线组→六线谱
#   ② 无谱线时看字符块：小而多且窄→简谱数字；中大方形块→方块字谱（减字谱/工尺，进一步靠斜杠密度粗分）
#   ③ 都不像→unknown（如实拒判，不硬猜）
# 用法: python3 工具_谱种路由.py <图> [--json 输出.json]
import argparse
import json
import os

import cv2
import numpy as np


def load_gray(path):
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise SystemExit(f'读不到图：{path}')
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
    # 谱表线数归判：恰 6 线→六线谱；5 的倍数→五线谱（多谱表连排）；5→五线；其余按五线存疑
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
        # 无谱线：先按墨量粗分（影印密排 vs 疏排印刷）
        _bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 10)
        ink = float((_bw > 0).mean())
        result['ink'] = round(ink, 4)
        if ink > 0.15:
            result.update(spec='影印密排谱（工尺/古籍类）', engine='SuziOMR（工尺）/ 需目核',
                          why=f'无谱线、墨量比高（{ink:.3f}，影印/密排特征）')
        elif n_blocks >= 60 and 0 < med_w <= w * 0.05 and med_h <= h * 0.06:
            # 小而多的块：简谱数字（数字通常窄矮）；方块字谱块更大
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
    r = route(a.img)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    if a.json:
        json.dump(r, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
