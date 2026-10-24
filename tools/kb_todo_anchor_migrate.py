#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb_todo_anchor_migrate — 99 总账行号锚 → 内容锚迁移（2026-10-24）

背景（知识库G2G4_范围盘点_2026-10-24.md 的 G2 节）：99-待办总账的分档清单
逐条登记以「行 N：〈引文〉」定位正文。各卷 10-13 建账后在行首入了修订头
「（最后修订：…｜…未核处标 [?]）」一行，全库 233 条锚点同步整体偏移 +1，
行号锚已全部失效。本脚本把 233 条登记统一改为内容锚：

    卷号·节标题「条目首句前 8 字」

口径（与 99 计数法说明同步写入）：
- 卷号 = 文件名去 .md（如 10-乐理与记谱、_总纲）
- 节标题 = 目标行所属的最近一个 ##/### 标题（按各卷正文现状实取，
  不靠 99 里的引文猜）；目标行自身在 ##/### 之前（卷首段）标「卷首」；
  目标行本身是标题的，节标题取该标题自身
- 首句前 8 字 = 目标行内容（含行首标记）前 8 字；组内重名不唯一时
  顺延至目标行更长前缀直至组内唯一，全文仍重名的加「②」
- 同行双「[?]」按一行一锚（243 处落点、233 条登记）
- 计数总表 12 行零改动，kb_todo_scan 按卷号正则照常对账

定位：目标物理行 = 登记「行 N」的 N+1（全库偏移 +1 为盘点实测值，
本脚本仍逐条复验「引文前 8 字 == 目标行前 8 字」，另加前 20 字核对，
失配即拒迁不落盘）。

用法:
  python3 tools/kb_todo_anchor_migrate.py               # 干跑，只出统计
  python3 tools/kb_todo_anchor_migrate.py --out 新账.md # 新账写文件，不动原账
  python3 tools/kb_todo_anchor_migrate.py --apply       # 校验全绿才落盘
幂等：落盘后重跑，检测不到「行 N：」登记即视为已迁移，0 改动退出。
退出码：0 通过；1 校验不过或参数错（不写盘）。
"""
import argparse
import os
import re
import sys
from collections import Counter, OrderedDict, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
KB = os.path.join(ROOT, '知识')
LEDGER = os.path.join(KB, '99-待办总账.md')

SECTION_RE = re.compile(r'^###\s+(.+?)\s*（(\d+)\s*处）\s*$')
ENTRY_RE = re.compile(r'^- \[ \] 行 (\d+)：(.*)$')
HEADING_RE = re.compile(r'^#{2,3}\s*(.*)$')     # ## / ### 即节标题

EXPECT_ENTRIES = 233
EXPECT_PER_VOL = {  # 盘点报告 G2 实测登记数分布
    '80-世界音乐.md': 101, '85-音乐史.md': 34, '87-音乐教育.md': 14,
    '10-乐理与记谱.md': 13, '70-风格体系.md': 11, '30-曲式.md': 10,
    '50-配器.md': 21, '40-复调.md': 9, '60-编配与即兴.md': 8,
    '20-和声.md': 7, '_总纲.md': 4, '90-音乐问答协议.md': 1,
}


def read_lines(path):
    data = open(path, 'r', encoding='utf-8', newline='').read()
    lines = data.split('\n')
    return lines, data


def parse_ledger(lines):
    """分档清单 → (有序节字典 {卷名: 首条登记行号}, 登记列表)"""
    entries = []
    cur = None
    for i, line in enumerate(lines):
        m = SECTION_RE.match(line)
        if m:
            cur = m.group(1)
            continue
        m = ENTRY_RE.match(line)
        if m and cur is not None:
            entries.append({
                'vol': cur, 'idx': i,
                'line_no': int(m.group(1)),      # 「行 N」里的 N
                'citation': m.group(2),
            })
    return entries


def classify(citation):
    s = citation.lstrip()
    if s.startswith('#'):
        return '标题'
    if s.startswith('|'):
        return '表格'
    if s.startswith('-'):
        return '清单'
    return '正文'


def locate_and_anchor(entries, vcache, errors):
    """逐条定位目标行、定节标题、定 8 字前缀；errors 收集全部失配。"""
    for e in entries:
        if e['vol'] not in vcache:
            vcache[e['vol']] = open(os.path.join(KB, e['vol']),
                                    encoding='utf-8', newline='').read().split('\n')
        vlines = vcache[e['vol']]
        target = vlines[e['line_no']].rstrip('\r')     # 行 N → 物理行 N+1
        c8 = e['citation'][:8]
        if not target.startswith(c8):
            errors.append('前缀失配 卷=%s 行=%s 引文前8字=%r 目标行=%r'
                          % (e['vol'], e['line_no'], c8, target[:8]))
            continue
        if not target.startswith(e['citation'][:20]):
            errors.append('前20字失配 卷=%s 行=%s 引文前20=%r 目标前20=%r'
                          % (e['vol'], e['line_no'],
                             e['citation'][:20], target[:20]))
            continue
        e['target_text'] = target
        # 节标题：从目标行自身往回找最近 ##/###
        section = None
        for j in range(e['line_no'], -1, -1):
            hm = HEADING_RE.match(vlines[j])
            if hm:
                section = hm.group(1)
                break
        if section is None:
            section = '卷首'
        e['section'] = section
        e['p8'] = target[:8]

    # 组内（卷·节）8 字前缀重名 → 按成对最长公共前缀顺延
    groups = defaultdict(list)
    for e in entries:
        if 'section' in e:
            groups[(e['vol'], e['section'])].append(e)
    for (vol, sec), group in groups.items():
        by8 = defaultdict(list)
        for e in group:
            by8[e['p8']].append(e)
        for p8, es in by8.items():
            if len(es) == 1:
                es[0]['anchor'] = '%s·%s「%s」' % (vol, sec, p8)
                continue
            texts = [e['target_text'].rstrip() for e in es]
            for e in es:
                t = e['target_text'].rstrip()
                peers = [x for x in texts if x is not t]
                n = len(p8)
                while True:
                    cand = t[:n + 1]
                    if n + 1 > len(t):
                        cand = t + '②'          # 全文也是他人前缀，加序号兜底
                        break
                    if not any(o.startswith(cand) for o in peers):
                        break
                    n += 1
                e['anchor'] = '%s·%s「%s」' % (vol, sec, cand)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='校验全绿后落盘')
    ap.add_argument('--out', default=None, help='新账写到此路径（不动原账）')
    args = ap.parse_args()

    lines, data = read_lines(LEDGER)
    entries = parse_ledger(lines)

    # 幂等：已是新锚口径
    if not entries and ENTRY_RE.search(data) is None:
        print('无「行 N：」登记——已是新锚口径，0 改动退出')
        return 0

    if len(entries) != EXPECT_ENTRIES:
        print('登记数 %d ≠ 预期 %d，拒迁' % (len(entries), EXPECT_ENTRIES))
        return 1
    got = Counter(e['vol'] for e in entries)
    bad = [v for v in EXPECT_PER_VOL if got.get(v, 0) != EXPECT_PER_VOL[v]]
    if bad:
        print('分卷登记数与盘点不符：%s' % bad)
        return 1

    errors = []
    vcache = OrderedDict()
    locate_and_anchor(entries, vcache, errors)

    cats = Counter(classify(e['citation']) for e in entries)
    sec_by_vol = Counter(e['section'] for e in entries)
    anchors = [e['anchor'] for e in entries]
    dup = [k for k, c in Counter(anchors).items() if c > 1]

    print('== 99 总账行号锚 → 内容锚迁移 ==')
    print('登记数：%d / 预期 %d，%s' % (len(entries), EXPECT_ENTRIES,
                                    '对' if len(entries) == EXPECT_ENTRIES else '错'))
    print('形态构成：标题 %d / 表格 %d / 清单 %d / 正文 %d'
          % (cats.get('标题', 0), cats.get('表格', 0),
             cats.get('清单', 0), cats.get('正文', 0)))
    print('节标题 去重 %d 个（最高五卷：%s）'
          % (len(set(sec_by_vol)), dict(sec_by_vol.most_common(5))))
    print('锚重复：%s' % (dup or '无'))
    print('失配：%d 条' % len(errors))
    for err in errors[:12]:
        print('  ! %s' % err)
    if errors or dup:
        print('校验不过，不落盘')
        return 1

    # 生成新账：只替换登记行
    new_lines = list(lines)
    for e in entries:
        new_lines[e['idx']] = '- [ ] %s：%s' % (e['anchor'], e['citation'])
    new_text = '\n'.join(new_lines)
    if data.endswith('\n') and not new_text.endswith('\n'):
        new_text += '\n'
    cnt_new = len(re.findall(r'^- \[ \] .+?「.+」：', new_text, re.M))
    cnt_old = len(re.findall(r'^- \[ \] 行 \d+：', new_text, re.M))
    print('替换后：新锚登记 %d 条 / 残余「行 N：」%d 条'
          % (cnt_new, cnt_old))

    if args.out:
        open(args.out, 'w', encoding='utf-8', newline='').write(new_text)
        print('新账已写 %s' % args.out)
    if args.apply:
        if cnt_new != EXPECT_ENTRIES or cnt_old != 0:
            print('替换数不合预期，拒绝落盘')
            return 1
        open(LEDGER, 'w', encoding='utf-8', newline='').write(new_text)
        print('已落盘 %s' % LEDGER)
    return 0


if __name__ == '__main__':
    sys.exit(main())