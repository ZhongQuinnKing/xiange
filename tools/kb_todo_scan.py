#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb_todo_scan — 知识库待办核销扫描（[?] 台账工具化）

逐行扫 知识/*.md 的 [?] 记号（页眉模板行「未核处标 [?]」不计），
出两样：①按档汇总（并与 99-待办总账 的计数表对照）②逐条清单（文件／行号／文本）。

用法: python3 tools/kb_todo_scan.py [--out 核销清单.md] [--json 汇总.json]
退出码：0 扫毕（有差处列入报告）
"""
import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
KB = os.path.join(ROOT, '知识')
LEDGER = os.path.join(KB, '99-待办总账.md')
HEADER_MARK = '未核处标 [?]'   # 页眉模板行内的这一处不计


def scan():
    per = {}
    items = []
    for f in sorted(glob.glob(os.path.join(KB, '*.md'))):
        name = os.path.basename(f)
        if name == '99-待办总账.md':
            continue
        n = 0
        for i, line in enumerate(open(f, encoding='utf-8'), 1):
            if '[?]' not in line:
                continue
            if HEADER_MARK in line:
                continue
            cnt = line.count('[?]')
            n += cnt
            items.append({'file': name, 'line': i, 'count': cnt,
                          'text': line.strip()[:120]})
        if n:
            per[name] = n
    return per, items


def ledger_table():
    tab = {}
    for line in open(LEDGER, encoding='utf-8'):
        m = re.match(r'\|\s*([\w\-]+\.md)\s*\|\s*(\d+)\s*\|', line)
        if m:
            tab[m.group(1)] = int(m.group(2))
    return tab


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=None, help='逐条清单写 Markdown')
    ap.add_argument('--json', default=None, help='汇总写 JSON')
    args = ap.parse_args()
    per, items = scan()
    tab = ledger_table()
    total = sum(per.values())
    print('== 核销扫描（[?] 字面计数；页眉模板行不计）==')
    keys = sorted(set(per) | set(tab))
    diffs = []
    for k in keys:
        a, b = per.get(k, 0), tab.get(k, None)
        mark = '对' if b == a else (f'差（账 {b}）' if b is not None else '账外')
        if b is not None and b != a:
            diffs.append(k)
        print(f'  {k}: 实点 {a}｜总账 {b if b is not None else "（未入账）"}｜{mark}')
    print(f'合计：实点 {total}｜总账合计 {sum(tab.values())}｜字面差处 {len(diffs)}')
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as fo:
            fo.write('# 知识库待办核销清单（kb_todo_scan 生成）\n\n')
            fo.write(f'实点合计 {total} 处（页眉模板行不计）；与总账差异：{diffs or "无"}\n\n')
            cur = None
            for it in items:
                if it['file'] != cur:
                    cur = it['file']
                    fo.write(f"\n## {cur}\n")
                fo.write(f"- 行 {it['line']}：{it['text']}\n")
        print(f'逐条清单已写 {args.out}（{len(items)} 条）')
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump({'per_file': per, 'ledger': tab, 'total': total,
                       'diffs': diffs, 'items': items}, f, ensure_ascii=False, indent=1)
        print(f'汇总 JSON 已写 {args.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
