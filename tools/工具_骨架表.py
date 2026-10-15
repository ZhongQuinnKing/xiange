#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具_骨架表.py —— 设计数据 → 一页缩谱（骨架表）。

用途：作曲流程的第一份产出。骨架表先立结构（调式、拍号、长度、逐小节和弦与
功能、低音、标注），确认后再展开音符；表从设计数据单一来源直出，保证表与曲
不会两处打架。
用法:
  python3 工具_骨架表.py <生成器.py> [输出.md]
  生成器里需有 SKELETON 与 CHORD_TONES 两个字面量（静态解析，不执行生成器）：
    SKELETON: {小节号: (和弦, 功能, 低音, 标注)} 或 {小节号: {版本名: (...)}}
              （版本名形态用于一部多版：同一小节按版本给不同行，None 表共用）
    CHORD_TONES: {和弦名: (音名, ...)}
  默认输出 <生成器名>_骨架表.md（同目录）。
"""
import ast
import os
import sys


def load_skeleton(gen_path):
    """静态解析生成器源码，取出 SKELETON 与 CHORD_TONES 两个字面量（不执行生成器）。"""
    tree = ast.parse(open(gen_path, encoding='utf-8').read())
    got = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = getattr(node.targets[0], 'id', None)
            if name in ('SKELETON', 'CHORD_TONES'):
                got[name] = ast.literal_eval(node.value)
    return got.get('SKELETON', {}), got.get('CHORD_TONES', {})


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    gen = sys.argv[1]
    if not os.path.exists(gen):
        print('生成器文件不存在：', gen)
        sys.exit(1)
    stem = os.path.splitext(os.path.basename(gen))[0]
    title = stem[3:] if stem.startswith('生成_') else stem
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.abspath(gen)), f'{stem}_骨架表.md')
    sk, tones = load_skeleton(gen)
    if not sk:
        print('未在生成器里找到 SKELETON 字面量；未生成')
        sys.exit(1)
    lines = [f'# 《{title}》一页缩谱（骨架表）', '']
    lines.append(f'来源：本表由 工具_骨架表.py 从 {os.path.basename(gen)} 的 SKELETON 段直出'
                 f'（单一数据源，改骨架改生成器）。')
    lines.append('')
    lines.append('| 小节 | 和弦 | 功能 | 低音 | 标注 | 版本 |')
    lines.append('|---|---|---|---|---|---|')
    for m in sorted(sk):
        entry = sk[m]
        if isinstance(entry, dict):
            for v, cell in entry.items():
                if cell is None:
                    continue
                chord, func, bass, note = cell
                lines.append(f'| {m} | {chord} | {func} | {bass} | {note} | {v} 版 |')
        else:
            chord, func, bass, note = entry
            lines.append(f'| {m} | {chord} | {func} | {bass} | {note} | 共享 |')
    lines.append('')
    lines.append('和弦音（CHORD_TONES）：')
    for chord, ts in tones.items():
        lines.append(f'- {chord}：{" ".join(ts)}')
    lines.append('')
    with open(out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'✓ 已生成：{out}')


if __name__ == '__main__':
    main()
