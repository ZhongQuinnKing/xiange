#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""notation_fix — 记谱规范后处理（符杠分组／符干方向；幂等）

用途：给直接以字符串模板产出 MusicXML 的生成器补一道"记谱规范化"后处理。
背景：生成器不写 <beam> 时，八分音符渲染成各自带符尾（♪♪♪♪），不符合器乐
      记谱规范；乐理检查（theory_check）与原谱对照查不出这一类问题——记谱
      规范是独立的一关（2026-10-10 立，N1/N2 的修复侧）。

规则（与 notation_check.py 同一口径）：
  1. 符杠分组：八分及更短音符按拍成组，拍内连续 ≥2 个连符杠，跨拍不连。
     4/4 即八分两两一组（按四分拍）；十六分在同拍内成组。
     复拍子（6/8、9/8、3/8）按附点单位成组。
     [?] 次级符杠（十六分的二级杠）按拍内细分做基础分组，本曲数据无十六分，未实测；
     [?] 复拍子与三连音场景未实测（三连音按拍外处理：不连杠、不并入）。
  2. 符干方向：双谱表 part 按谱表——staff 1 向上、staff 2 向下；无 staff 标记的
     多 part 谱按 part 序——第一 part 向上、其余向下。全曲统一写死。
     全音符无符干（不写）；休止符不写符干。
  3. 幂等：重跑先清旧符杠/符干，再按当前规则重建。默认走文本手术——只增删
     <stem>/<beam> 两类行，其余字节不动；笔记块结构与解析计数对不上时退回
     整树重写（会重新缩进，丢失 DOCTYPE，须留意）。

不做的事：不改音高、时值、声部、谱表归属；休止符布局与谱表分配只由
          notation_check.py 检查，不在本器自动改写（改写会动节奏语义，须人裁）。

用法:
    python3 notation_fix.py <文件.musicxml> [更多文件...]   # 原地规范化
    python3 notation_fix.py --dry-run <文件...>            # 只报告，不写盘
API: normalize_file(path, dry_run=False) -> dict 报告
     normalize_xml_bytes(data) -> (data, 报告)
"""
import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

IND = '        '   # 元素行缩进（与生成器同款：8 空格）


def _t(el):
    return el.tag.split('}')[-1] if isinstance(el.tag, str) else ''


def _find(el, name):
    for c in el:
        if _t(c) == name:
            return c
    return None


def _findtext(el, name):
    c = _find(el, name)
    return (c.text or '') if c is not None else None


# ---------------- 时间与分组 ----------------

def _beam_unit_quarters(beats, beat_type):
    """一个连杠组的时间宽度（四分音符数）。4/4 → 1.0；6/8 → 1.5；3/8 → 1.5。"""
    unit = 4.0 / beat_type
    if beat_type == 8 and beats % 3 == 0:
        unit *= 3
    return unit


def _collect(part):
    """收集一个 part 的小节→事件序列。

    返回 [(mno, seq, div, unit_q)]：
      seq 为 ('note', e) / ('break',)：e 含 onset/dur/rest/voice/staff/el/type。
      和弦成员（带 <chord/>）不入 seq（随主音符）；<backup>/<forward> 记 break。
    """
    out = []
    div = None
    beats, beat_type = 4, 4
    for meas in [c for c in part if _t(c) == 'measure']:
        for a in [c for c in meas if _t(c) == 'attributes']:
            d = _findtext(a, 'divisions')
            if d:
                div = int(float(d))
            for t in [c for c in a if _t(c) == 'time']:
                b, bt = _findtext(t, 'beats'), _findtext(t, 'beat-type')
                if b and bt:
                    beats, beat_type = int(float(b)), int(float(bt))
        if div is None:
            continue
        pos = 0.0
        seq = []
        for el in list(meas):
            tag = _t(el)
            if tag == 'backup':
                pos -= float(_findtext(el, 'duration') or 0)
                seq.append(('break', None))
            elif tag == 'forward':
                pos += float(_findtext(el, 'duration') or 0)
                seq.append(('break', None))
            elif tag == 'note':
                if _find(el, 'chord') is not None:
                    continue                      # 和弦成员：不单独入组
                if _find(el, 'grace') is not None:
                    seq.append(('break', None))   # 装饰音：不连、断开
                    continue
                dur = float(_findtext(el, 'duration') or 0)
                e = dict(onset=pos, dur=dur,
                         rest=(_find(el, 'rest') is not None),
                         voice=(_findtext(el, 'voice') or '1'),
                         staff=(_findtext(el, 'staff')),
                         type=(_findtext(el, 'type') or ''),
                         tup=(_find(el, 'time-modification') is not None),
                         el=el)
                seq.append(('note', e))
                pos += dur
        out.append((meas.get('number') or str(len(out) + 1), seq, div,
                    _beam_unit_quarters(beats, beat_type)))
    return out


def _groups_of(seq, div, unit_q):
    """把事件序列切成连杠组（≥2 个八分及更短音符，同拍同声部）。"""
    groups, cur = [], []

    def flush():
        if len(cur) >= 2:
            groups.append(list(cur))
        cur.clear()

    for kind, e in seq:
        if kind == 'break':
            flush()
            continue
        ql = e['dur'] / div
        if e['rest'] or e['tup'] or ql <= 0 or ql >= 1.0 - 1e-9:
            flush()
            continue
        if cur:
            p = cur[-1]
            same_unit = int((e['onset'] / div) // unit_q) == int((p['onset'] / div) // unit_q)
            same_voice = (e['voice'], e['staff']) == (p['voice'], p['staff'])
            if not (same_unit and same_voice):
                flush()
        cur.append(e)
    flush()
    return groups


def _plan(part, part_index):
    """算出一个 part 的逐音符方案：id(el) -> dict(stem=?, beams=[...])。"""
    plan = {}
    n_groups = n_beamed = n_stem = 0
    for _mno, seq, div, unit_q in _collect(part):
        groups = _groups_of(seq, div, unit_q)
        for g in groups:
            n = len(g)
            for i, e in enumerate(g):
                e['beam1'] = 'begin' if i == 0 else ('end' if i == n - 1 else 'continue')
            # 次级符杠：组内连续十六分（≤0.25 四分）段，段长 ≥2 连二级杠 [? 未实测]
            i = 0
            while i < n:
                if g[i]['dur'] / div <= 0.25 + 1e-9:
                    j = i
                    while j + 1 < n and g[j + 1]['dur'] / div <= 0.25 + 1e-9:
                        j += 1
                    if j > i:
                        for k in range(i, j + 1):
                            g[k]['beam2'] = ('begin' if k == i else
                                             ('end' if k == j else 'continue'))
                    i = j + 1
                else:
                    i += 1
            n_groups += 1
            n_beamed += n
        for _k, e in seq:
            if _k != 'note':
                continue
            el = e['el']
            item = plan.setdefault(id(el), {'stem': None, 'beams': []})
            if e.get('beam1'):
                item['beams'].append(('1', e['beam1']))
                if e.get('beam2'):
                    item['beams'].append(('2', e['beam2']))
            if not e['rest'] and e['type'] not in ('whole', 'breve', 'long'):
                if e['staff'] is not None:
                    d = 'up' if int(e['staff']) <= 1 else 'down'
                else:
                    d = 'up' if part_index == 0 else 'down'
                item['stem'] = d
                n_stem += 1
    return plan, dict(groups=n_groups, beamed_notes=n_beamed, stem_notes=n_stem)


# ---------------- 文本手术 ----------------

_NOTE_BLOCK = re.compile(r'<note>.*?</note>', re.S)
_OLD_STEM = re.compile(r'[ \t]*<stem>[^<]*</stem>[ \t]*\n')
_OLD_BEAM = re.compile(r'[ \t]*<beam\b[^>]*>[^<]*</beam>[ \t]*\n')


def _edit_block(block, stem, beams):
    """重建单个 <note> 块：先清旧 stem/beam 行，再按方案插入。
    2026-10-10 夜修（隔离验证抓出）：单行格式（整元素一行、紧凑生成器常见）走行内手术——
    旧逻辑假定块末行是独立闭合行，单行块下会把 stem/beam 插到 note 元素之外（静默写坏、不幂等）。"""
    if '\n' not in block.strip():
        s = re.sub(r'<stem>[^<]*</stem>', '', block)
        s = re.sub(r'<beam\b[^>]*>[^<]*</beam>', '', s)
        if stem is None and not beams:
            return s
        beam_s = ''.join(f'<beam number="{num}">{val}</beam>' for num, val in beams)
        if '<staff>' in s:
            # 按 DTD 顺序：stem 在 staff 前、beam 在 staff 后
            if stem:
                s = s.replace('<staff>', f'<stem>{stem}</stem><staff>', 1)
            if beam_s:
                s = re.sub(r'(<staff>[^<]*</staff>)', lambda mm: mm.group(1) + beam_s, s, count=1)
            return s
        ins = (f'<stem>{stem}</stem>' if stem else '') + beam_s
        return s.replace('</note>', ins + '</note>', 1)
    stripped = _OLD_BEAM.sub('', _OLD_STEM.sub('', block))
    if stem is None and not beams:
        return stripped
    stem_line = f'{IND}<stem>{stem}</stem>' if stem else None
    beam_lines = [f'{IND}<beam number="{num}">{val}</beam>' for num, val in beams]
    lines = stripped.split('\n')
    last = len(lines) - 1
    staff_idx = None
    for i, l in enumerate(lines):
        if l.strip().startswith('<staff>'):
            staff_idx = i
            break
    out = []
    for i, l in enumerate(lines):
        if staff_idx is None and i == last:
            if stem_line:
                out.append(stem_line)
            out.extend(beam_lines)
            out.append(l)
        elif staff_idx is not None and i == staff_idx:
            if stem_line:
                out.append(stem_line)
            out.append(l)
            out.extend(beam_lines)
        else:
            out.append(l)
    return '\n'.join(out)


def _fallback_tree(root, plan):
    """笔记块结构不匹配时的整树重写（丢 DOCTYPE，重新缩进）。"""
    for el in root.iter():
        if _t(el) != 'note':
            continue
        item = plan.get(id(el), {'stem': None, 'beams': []})
        for name in ('stem', 'beam'):
            for c in [c for c in el if _t(c) == name]:
                el.remove(c)
        stem_el = None
        if item['stem']:
            stem_el = ET.Element('stem')
            stem_el.text = item['stem']
        beam_els = []
        for num, val in item['beams']:
            b = ET.Element('beam', {'number': num})
            b.text = val
            beam_els.append(b)
        # 按 DTD 顺序：stem 在 staff 前、beam 在 staff 后
        staff_pos = None
        for i, c in enumerate(el):
            if _t(c) == 'staff':
                staff_pos = i
                break
        if staff_pos is not None:
            at = staff_pos
            if stem_el is not None:
                el.insert(at, stem_el)
                at += 1
            at += 1                     # 越过 staff 元素本身
            for b in beam_els:
                el.insert(at, b)
                at += 1
        else:
            if stem_el is not None:
                el.append(stem_el)
            for b in beam_els:
                el.append(b)
    ET.indent(root, space='  ')
    body = ET.tostring(root, encoding='unicode')
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body


def normalize_xml_bytes(data):
    """核心：输入 MusicXML 字节，返回（规范化后文本, 报告 dict）。"""
    root = ET.fromstring(data)
    parts = [c for c in root if _t(c) == 'part']
    plan, rep = {}, dict(groups=0, beamed_notes=0, stem_notes=0)
    for pi, part in enumerate(parts):
        p, r = _plan(part, pi)
        for k in rep:
            rep[k] += r[k]
        plan.update(p)
    text = data.decode('utf-8') if isinstance(data, bytes) else data
    blocks = list(_NOTE_BLOCK.finditer(text))
    notes = [el for el in root.iter() if _t(el) == 'note']
    rep['mode'] = 'text'
    if len(blocks) == len(notes):
        pieces, changed = [], 0
        pos = 0
        for m, el in zip(blocks, notes):
            item = plan.get(id(el), {'stem': None, 'beams': []})
            new = _edit_block(m.group(0), item['stem'], item['beams'])
            if new != m.group(0):
                changed += 1
            pieces.append(text[pos:m.start()])
            pieces.append(new)
            pos = m.end()
        pieces.append(text[pos:])
        rep['changed_blocks'] = changed
        text = ''.join(pieces)
    else:
        rep['mode'] = 'tree'
        rep['changed_blocks'] = len(notes)
        text = _fallback_tree(root, plan)
    return text, rep


def normalize_file(path, dry_run=False):
    """就地把文件规范化；dry_run=True 只报告。"""
    with open(path, 'rb') as f:
        data = f.read()
    text, rep = normalize_xml_bytes(data)
    rep['file'] = os.path.basename(path)
    rep['wrote'] = False
    if not dry_run:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(text)
        os.replace(tmp, path)
        rep['wrote'] = True
    return rep


def main():
    ap = argparse.ArgumentParser(description='记谱规范后处理（符杠分组／符干方向）')
    ap.add_argument('files', nargs='+', help='MusicXML 文件')
    ap.add_argument('--dry-run', action='store_true', help='只报告，不写盘')
    ap.add_argument('--json', help='汇总写 JSON（供机读）')
    args = ap.parse_args()
    reps = []
    for p in args.files:
        if not os.path.exists(p):
            sys.stderr.write(f'读谱失败：{p} 不存在（参数为 MusicXML 文件路径）\n')
            sys.exit(2)
        rep = normalize_file(p, dry_run=args.dry_run)
        reps.append(rep)
        flag = '（dry-run 未写盘）' if args.dry_run else ''
        print(f'[记谱规范] {rep["file"]}：符杠组 {rep["groups"]}、带杠音 {rep["beamed_notes"]}、'
              f'符干 {rep["stem_notes"]}、改写块 {rep["changed_blocks"]}'
              f'（{rep["mode"]} 法）{flag}')
    if args.dry_run:
        print('注：dry-run 只报告不改动。')
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(reps, f, ensure_ascii=False, indent=1)
        print(f'（JSON 已写 {args.json}）')


if __name__ == '__main__':
    main()
