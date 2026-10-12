# -*- coding: utf-8 -*-
# 甲路自训·guqinMM 树 → 结构化类名 转换器 v3（2026-10-10）
# v3 相对 v2：数字对合并（⿱(5,6)→"56" 五徽六分；⿱(10,2)→"102"）。结构感知抽取。
# 输出：v3 产出 CSV（image, classname, code, split）+ 统计
# 标签格式：{前缀_}{左字+徽分}{后缀}_{右字+弦} / {前缀_}散音_{右字+弦} / {前缀_}{右字+弦}
# 与 auto-dapu 格式同构（如 夕108_勾3 / 大8上_綽_勾4 / 散音_挑5 / 注_勾4）

import ast
import collections
import csv
import os

BASE = os.path.expanduser('~/Desktop/AI工具/guqinMM/guqin_jzp/JZPNet/data/jzp')
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
ARITY = {'⿱': 2, '⿰': 2, '⿸': 2, '⿺': 2, '⿹': 2, '⿲': 3, '⿳': 3}

LEFT_MAP = {
    'LEFT_FINGER_DA': '大', 'LEFT_FINGER_MING': '夕', 'LEFT_FINGER_SHI': '人',
    'LEFT_FINGER_SHI_2': '人', 'LEFT_FINGER_ZHONG': '中', 'LEFT_FINGER_WU': '无',
    'LEFT_FINGER_GUI': '跪',
}
RIGHT_MAP = {
    'RIGHT_TIAO': '挑', 'RIGHT_GOU': '勾', 'RIGHT_MO': '抹', 'RIGHT_TI': '剔',
    'RIGHT_TI_2': '剔', 'RIGHT_DA': '打', 'RIGHT_ZHAI': '摘', 'RIGHT_TUO': '托',
    'RIGHT_BI': '擘', 'RIGHT_LI': '历', 'RIGHT_JUAN': '蠲', 'RIGHT_JUAN_2': '蠲',
    'RIGHT_LUN': '轮', 'RIGHT_SUO': '锁', 'RIGHT_CHANGSUO': '长锁',
}
PREFIX_MAP = {'LEFT_ZHU': '注', 'LEFT_ZHU_2': '注', 'LEFT_CHUO': '綽', 'LEFT_CHUO_2': '綽', 'LEFT_JIU': '就'}
SUFFIX_MAP = {'LEFT_SHANG': '上', 'LEFT_XIA': '下'}
FAN_TOKENS = {'TECHNIQUE_FAN_YIN', 'TECHNIQUE_FAN_QI', 'TECHNIQUE_FAN_ZHI'}


def parse_polish(tokens):
    if not tokens:
        return None, 0
    t = tokens[0]
    if t in ARITY:
        cs = []; i = 1
        for _ in range(ARITY[t]):
            c, u = parse_polish(tokens[i:]); cs.append(c); i += u
        return (t, cs), i
    return t, 1


def collect_digits(node):
    """子树里全部数字叶子（按序）。"""
    if isinstance(node, str):
        return [node] if node.isdigit() else []
    out = []
    for c in node[1]:
        out += collect_digits(c)
    return out


def find_finger_pair(tree, box):
    """找 (op, [...finger..., ...数字容器...]) → (finger, num_str)。
    num_str：容器全数字时合并（56/102），否则取第一个数字。"""
    result = [None]
    def rec(node):
        if not isinstance(node, tuple) or result[0]:
            return
        op, cs = node
        for i, c in enumerate(cs):
            if isinstance(c, str) and c in box:
                # 找兄弟里的数字来源（优先紧邻的）
                for j in list(range(i+1, len(cs))) + list(range(i-1, -1, -1)):
                    if j == i:
                        continue
                    digs = collect_digits(cs[j])
                    if digs:
                        def all_leaves(n):
                            if isinstance(n, str):
                                return [n]
                            out = []
                            for c in n[1]:
                                out += all_leaves(c)
                            return out
                        lv = all_leaves(cs[j])
                        pure = all(x.isdigit() for x in lv)
                        if len(digs) == 2 and pure and len(digs[0]) <= 2 and len(digs[1]) <= 2:
                            num = digs[0] + digs[1]  # 徽分合并：5,6 → 56
                        else:
                            num = digs[0]
                        result[0] = (c, num)
                        return
        for c in cs:
            rec(c)
    rec(tree)
    return result[0] or (None, None)


def to_classname(lf, ln, rf, rn, prefix, suffix, fan, san, n_right_extra, seq):
    lm = LEFT_MAP.get(lf, '') if lf else ''
    rm = RIGHT_MAP.get(rf, '') if rf else ''
    pfx = PREFIX_MAP.get(prefix, '') if prefix else ''
    sfx = SUFFIX_MAP.get(suffix, '') if suffix else ''
    if fan:
        return None, 'out_fan'
    if n_right_extra > 1:
        return None, 'out_group'   # 复组＝两根以上右手指法（n_right_extra 是右手 token 总数）
    if san:
        if rf and rn:
            return (f"{pfx+'_' if pfx else ''}散音_{rm}{rn}"), 'ok_san'
        return None, 'san_no_right'
    if lf and ln and rf and rn:
        lp = f"{lm}{ln}{sfx}"
        if pfx:
            return f"{pfx}_{lp}_{rm}{rn}", 'ok_an_pfx'
        return f"{lp}_{rm}{rn}", 'ok_an'
    if rf and rn and not lf:
        return f"{pfx+'_' if pfx else ''}{rm}{rn}", 'ok_context'
    if not lf and not rf:
        nums = [t for t in seq if isinstance(t, str) and t.isdigit()]
        if nums:
            return nums[0], 'bare_num'
    return None, 'pattern_miss'


def extract(tree):
    lf, ln = find_finger_pair(tree, LEFT_MAP)
    rf, rn = find_finger_pair(tree, RIGHT_MAP)
    # 第二右手（复组检测）
    def count_right(node):
        if isinstance(node, str):
            return 1 if node in RIGHT_MAP else 0
        return sum(count_right(c) for c in node[1])
    nth = count_right(tree)
    seq = []
    def rec2(node):
        if isinstance(node, str):
            seq.append(node)
        else:
            for c in node[1]:
                rec2(c)
    rec2(tree)
    prefix = next((t for t in seq if t in PREFIX_MAP), None)
    suffix = next((t for t in seq if t in SUFFIX_MAP), None)
    fan = any(t in FAN_TOKENS for t in seq)
    san = 'TECHNIQUE_SAN_YIN' in seq
    return lf, ln, rf, rn, prefix, suffix, fan, san, nth, seq


def main():
    splits = ['wushen_train', 'test', 'wushen_1', 'wushen_aug', 'zyt']
    ada = set()
    for r in csv.DictReader(open(os.path.expanduser('~/Desktop/AI工具/guqin-auto-dapu/data/data.csv'), encoding='cp932')):
        ada.add(r['radical_name'])
    rows = []
    grand = collections.Counter()
    for sub in splits:
        fp = os.path.join(BASE, sub, 'metadata_3.txt')
        if not os.path.exists(fp):
            continue
        stats = collections.Counter()
        for line in open(fp, encoding='utf-8'):
            if line.startswith('id\t') or not line.strip():
                continue
            parts = line.rstrip('\n').split('\t')
            if len(parts) < 2:
                continue
            img = parts[0].split('/')[-1]
            try:
                lst = ast.literal_eval(parts[1])
                toks = [t for t in lst if t != 'Music']
                tree, _ = parse_polish(toks)
                fields = extract(tree)
                name, code = to_classname(*fields[:8], fields[8], fields[9])
            except Exception:
                stats['parse_fail'] += 1
                continue
            stats[code] += 1
            grand[code] += 1
            if name:
                rows.append((sub, img, name, code))
        total = sum(stats.values())
        ok = sum(stats[k] for k in ('ok_an', 'ok_san', 'ok_context', 'ok_an_pfx'))
        print(f'== {sub}: {total} | 映射 {ok} ({ok/total*100:.1f}%) | {dict(stats)}')

    total = sum(grand.values())
    ok = sum(grand[k] for k in ('ok_an', 'ok_san', 'ok_context', 'ok_an_pfx'))
    names = collections.Counter(r[2] for r in rows)
    hit = sum(1 for r in rows if r[2] in ada)
    print(f'\n=== 全量 {total} | 可映射 {ok} ({ok/total*100:.1f}%) ===')
    print(f'明细: {dict(grand)}')
    print(f'类名 {len(names)} 种；命中 auto-dapu {sum(1 for n in names if n in ada)} 种；命中样本 {hit}')
    print(f'类名前档 {names.most_common(8)}')
    with open(os.path.join(OUT_DIR, '树转换_v3_产出.csv'), 'w', newline='', encoding='utf-8') as fo:
        w = csv.writer(fo)
        w.writerow(['split', 'image', 'classname', 'code'])
        w.writerows(rows)
    print(f'已写 树转换_v3_产出.csv（{len(rows)} 行）')


if __name__ == '__main__':
    main()
