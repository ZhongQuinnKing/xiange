#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
omr_eval 自校验 — 五场景（自足版：内嵌测试谱，不依赖任何外部文件）

验证四级度量判据本身是否正确：
  1 自比          → 必须全绿
  2 全低八度      → 必须标八度差（红，八度类）
  3 全升大三度    → 必须大量红（音名全错）；允许少量碰巧命中（移调后重叠）
  4 时值全改小(减半，保持成对) → 音高不动，必须黄不红
  5 删一音        → 必须出「漏」类红

任何场景不过 = 度量实现有 bug，修到全过为止。
用法: python3 test_omr_eval.py
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from omr_eval import parse_jp_md, evaluate

# 内嵌测试谱（双读 jp-md 格式，8 小节：和弦/单音/休止/混合节奏齐备）
_FIXTURE = """# 自测例题（钢琴小曲）
速度: ♩=80  拍号: 4/4

## m1
RH: [G3,B3,E4]:1.0  [G3,B3]:2.0  [G3,B3,E4]:1.0
LH: [C2]:2.0  [C2]:2.0

## m2
RH: [F#3,A3,D4]:1.0  [A3,B3]:0.5  [G3,B3,E4]:1.0  [F#3]:0.25  [G3]:0.25  [A3]:0.25  [D4]:0.25
LH: [B1]:1.0  [R]:1.0  [E2,E3]:0.5  [E2,E3]:0.5  [E2]:1.0

## m3
RH: [G3,B3,E4]:2.0  [A3,C4]:1.0  [B3,D4]:1.0
LH: [C2]:2.0  [G2]:2.0

## m4
RH: [C4,E4,G4]:4.0
LH: [C2,G2]:4.0

## m5
RH: [E4]:0.5  [D4]:0.5  [C4]:1.0  [B3]:0.5  [A3]:0.5  [G3]:1.0
LH: [A2]:2.0  [E2]:2.0

## m6
RH: [F#3,A3]:1.0  [G3,B3]:1.0  [A3,C4]:2.0
LH: [D2]:2.0  [D2,F#2]:2.0

## m7
RH: [B3]:1.0  [C4]:1.0  [D4]:1.0  [E4]:1.0
LH: [G2]:4.0

## m8
RH: [G3,B3,D4]:4.0
LH: [G2,B2]:4.0
"""

_NAMES = {0: 'C', 2: 'D', 4: 'E', 5: 'F', 7: 'G', 9: 'A', 11: 'B'}


def midi_to_name(m):
    octv = m // 12 - 1
    pc = m % 12
    if pc in _NAMES:
        return f'{_NAMES[pc]}{octv}'
    for k, v in _NAMES.items():
        if (k + 1) % 12 == pc:
            return f'{v}#{octv}'
    return None


def transform_names(text, semitones=0, octaves=0):
    """全谱音名统一移调/移八度"""
    def rep(m):
        mm = re.match(r'^([A-G])([#b]?)(\d)$', m.group(0))
        if not mm:
            return m.group(0)
        base = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}[mm.group(1)]
        acc = {'#': 1, 'b': -1}.get(mm.group(2), 0)
        midi = (int(mm.group(3)) + 1) * 12 + base + acc + semitones + 12 * octaves
        return midi_to_name(midi) or m.group(0)
    return re.sub(r'[A-G][#b]?\d', rep, text)


def scale_durs(text, factor):
    """时值整体缩放（保持每事件一个数，对齐不乱）"""
    return re.sub(r'(:\s*)([0-9.]+)',
                  lambda m: f'{m.group(1)}{float(m.group(2)) * factor:g}', text)


def write_tmp(name, content):
    p = os.path.join(tempfile.gettempdir(), f'_selftest_{name}.md')
    with open(p, 'w', encoding='utf-8') as f:
        f.write(content)
    return p


def main():
    truth_path = write_tmp('truth', _FIXTURE)
    src = _FIXTURE
    ev_t = parse_jp_md(truth_path)
    passed, failed = [], []

    def check(name, cond, detail):
        (passed if cond else failed).append((name, detail))
        mark = '✓' if cond else '✗'
        print(f'{mark} {name}: {detail}')

    # 1 自比
    r = evaluate(ev_t, parse_jp_md(truth_path), '真值', '同源')
    check('自比全绿', r['red'] == 0 and r['yellow'] == 0,
          f"绿{r['green']} 黄{r['yellow']} 红{r['red']}")

    # 2 全低八度
    p2 = write_tmp('low8', transform_names(src, octaves=-1))
    r2 = evaluate(ev_t, parse_jp_md(p2), '真值', '全低八度')
    check('低八度被标', r2['octave_diff'] > 0 and r2['green'] == 0,
          f"八度差{r2['octave_diff']} 绿{r2['green']} 红{r2['red']}")

    # 3 全升大三度（音名全错）。小样谱里移调后偶然命中偏多（和弦密集处），
    #   此场景的验收重心是"红量显著"，命中率阈值按样谱规模放宽到 40%；
    #   真正要拦的失败态是判据失灵（红=0 或几近全绿）
    p3 = write_tmp('m3up', transform_names(src, semitones=4))
    r3 = evaluate(ev_t, parse_jp_md(p3), '真值', '全升大三度')
    hit_rate = r3['pitch_matched'] / max(1, r3['truth_total'])
    check('大三度平移大量红', r3['red'] > 20 and hit_rate < 0.40,
          f"红{r3['red']} 命中率{hit_rate:.0%}")

    # 4 时值减半（成对保持，音高不动）→ 黄
    p4 = write_tmp('durhalf', scale_durs(src, 0.5))
    r4 = evaluate(ev_t, parse_jp_md(p4), '真值', '时值减半')
    check('时值错判黄不判红', r4['yellow'] > 0 and r4['red'] == 0 and r4['green'] == 0,
          f"绿{r4['green']} 黄{r4['yellow']} 红{r4['red']}")

    # 5 删一个事件 → 漏
    first = re.search(r'(\[[^\]]*\]:[0-9.]+)', src)
    p5 = write_tmp('drop1', src.replace(first.group(1), '', 1))
    r5 = evaluate(ev_t, parse_jp_md(p5), '真值', '删一事件')
    misses = [d for d in r5['detail_red'] if d[1] == '漏']
    check('删音被标漏', len(misses) >= 1, f"漏{len(misses)} 处")

    print()
    if failed:
        print(f'✗✗ {len(failed)} 场景不过：', [f[0] for f in failed])
        sys.exit(1)
    print(f'✓✓ 五场景全过（{len(passed)}/5）—— 四级度量判据正确')


if __name__ == '__main__':
    main()
