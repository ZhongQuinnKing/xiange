#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_check — 文档与实况对账（防数字漂移，CI 挂载）

查四类：
  1 套数：README 两处「判据级 N 套」与 CI 步骤名英文数词，须等于 tools/tests/test_*.py 实际数量
  2 工具表：README 工具表所列 .py 须与 tools/*.py 实际文件双向一致
  3 引用：README／SKILL／CONTRIBUTING／ROADMAP／docs 内的 docs/NN、知识/NN、tools/x.py、
    examples/xx 引用须可解析（缺失即红）
  4 公开语汇：全仓文本不得含内部协作语汇（黑名单见下；清单随发现增补，规矩见 CONTRIBUTING）

用法: python3 tools/doc_check.py [--json 报告.json]
退出码：0 全对 ／ 1 有差异
"""
import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

CN_NUM = {'十': 10, '十一': 11, '十二': 12, '十三': 13, '十四': 14,
          '十五': 15, '十六': 16, '十七': 17, '十八': 18, '十九': 19, '二十': 20}
EN_NUM = {'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14,
          'fifteen': 15, 'sixteen': 16, 'seventeen': 17, 'eighteen': 18,
          'nineteen': 19, 'twenty': 20}


def check_suite_count(issues):
    n = len(glob.glob(os.path.join(HERE, 'tests', 'test_*.py')))
    readme = open(os.path.join(ROOT, 'README.md'), encoding='utf-8').read()
    for m in re.finditer(r'判据级([一二三四五六七八九十]+)套', readme):
        got = CN_NUM.get(m.group(1))
        if got != n:
            issues.append(f'README「判据级{m.group(1)}套」≠ 实际 {n} 套')
    wf = open(os.path.join(ROOT, '.github', 'workflows', 'check.yml'), encoding='utf-8').read()
    for m in re.finditer(r'Run self-tests \(([a-z]+) suites\)', wf):
        got = EN_NUM.get(m.group(1))
        if got != n:
            issues.append(f'CI 步骤名「{m.group(1)} suites」≠ 实际 {n} 套')
    return n


def check_tool_table(issues):
    actual = {f for f in os.listdir(HERE) if f.endswith('.py')}
    readme = open(os.path.join(ROOT, 'README.md'), encoding='utf-8').read()
    listed = set(re.findall(r'^\|\s*([^\s|]+\.py)\s*\|', readme, re.M))
    for f in sorted(actual - listed):
        issues.append(f'工具 {f} 未入 README 工具表')
    for f in sorted(listed - actual):
        issues.append(f'README 工具表列了不存在的 {f}')
    return len(actual)


def check_refs(issues):
    pat = re.compile(r'(docs/[^\s,，。；、）)】\]"`「」]*|知识/[^\s,，。；、）)】\]"`「」]*'
                     r'|tools/[A-Za-z_0-9]+\.py|examples/[^\s,，。；、）)】\]"`]*)')
    files = (['README.md', 'SKILL.md', 'CONTRIBUTING.md', 'ROADMAP.md']
             + glob.glob(os.path.join(ROOT, 'docs', '*.md')))
    checked = 0
    for f in files:
        t = open(f, encoding='utf-8').read()
        for m in pat.findall(t):
            r = re.split(r'[（(：:]', m.rstrip('。：:、，'))[0].rstrip('。：:、，')
            checked += 1
            full = os.path.join(ROOT, r)
            if os.path.exists(full) or os.path.exists(full + '.md'):
                continue
            if re.match(r'(docs|知识)/[0-9]{2}', r) and glob.glob(os.path.join(ROOT, r + '*')):
                continue
            issues.append(f'{os.path.relpath(f, ROOT)} 引用不可解析：{r}')
    return checked


# 模式词面以 \u 转义拼装（re 支持）：扫描器自身不得把词面带进仓
VOCAB_BLACKLIST = [
    (r'指令[_\-－]\s*\d+', '内部指令编号'),
    (r'\u97f3\u4e50\u6280\u80fd\u5305\u002d\u5185\u90e8', '内部目录名'),
    (r'Desktop[/\\][\u8f6c\u8f49]\u8c31', '内部开发路径'),
    (r'\u7a97\u53e3\u603b\u8c03\u5ea6', '内部台账名'),
    (r'\u5c11\u7237|\u8587\u8587|\u5143\u82f1', '私人称谓'),
    (r'\u5929\u9009', '内部设备代号'),
]
VOCAB_SCAN_EXT = ('.py', '.md', '.yml', '.yaml', '.json', '.txt', '.sh')
VOCAB_SKIP_DIRS = ('.git', '__pycache__', '.ruff_cache')


def check_public_vocab(issues):
    """第 4 类：全仓扫内部语汇黑名单（2026-10-13 立，源自外部审读发现的件号残留）。"""
    hits = 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in VOCAB_SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith(VOCAB_SCAN_EXT):
                continue
            if fn == 'doc_check.py':  # 本文件含黑名单模式串本身，跳过自身
                continue
            fp = os.path.join(dirpath, fn)
            try:
                t = open(fp, encoding='utf-8', errors='ignore').read()
            except OSError:
                continue
            for pat, why in VOCAB_BLACKLIST:
                m = re.search(pat, t)
                if m:
                    rel = os.path.relpath(fp, ROOT)
                    issues.append(f'{rel} 含内部语汇（{why}）：{m.group(0)[:40]}')
                    hits += 1
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', help='报告写 JSON')
    args = ap.parse_args()
    issues = []
    n = check_suite_count(issues)
    m = check_tool_table(issues)
    refs = check_refs(issues)
    check_public_vocab(issues)
    print(f'套数 {n}｜工具 {m} 件｜引用抽查 {refs} 处｜差异 {len(issues)} 项')
    for i in issues:
        print('  ✗', i)
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump({'suites': n, 'tools': m, 'refs': refs, 'issues': issues},
                      f, ensure_ascii=False, indent=1)
    if issues:
        print('对账不过：文档与实况不一致，请同步（doc_check 是数字漂移的机械闸）。')
        return 1
    print('对账全过。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
