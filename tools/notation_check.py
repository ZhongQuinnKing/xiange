#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""notation_check — 记谱规范检器（护城河第⑤层：记谱层。2026-10-10 立）

乐理关查"音乐对不对"（theory_check），原谱关查"还是不是这首曲子"，
记谱关查"谱面写没写对"——三件不同的事。本关的立项起因：全曲八分无连符杠
（渲染成各自带符尾），theory_check 与原谱对照全绿放行，属全新盲区。

规则清单 v1（来源：器乐记谱通用规范；修复侧见 notation_fix.py，同一口径）：

  N1a 符杠缺失     —— 同拍内连续 ≥2 个八分及更短音符未被同一符杠链连住（严重）
  N1b 符杠分组不符 —— 符杠链与按拍分组不一致（跨拍连杠、孤音带杠、链残缺）（轻）
  N2a 符干不齐     —— 同一符杠链内符干方向不一致（严重）
  N2b 符干方向偏离 —— 钢琴双谱表约定：staff1 应向上、staff2 应向下（轻）
  N3a 二分休止越拍 —— 4/4（6/4）中二分休止不在第 1／3 拍起（轻）
  N3b 全休止符位置 —— 全休止不在小节首或不满整小节（轻）
  N3c 拍内休止未合并 —— 一拍内 ≥2 个休止符恰好填满该拍，宜合并书写（轻）
  N4a 谱表归属缺失 —— 声明 staves≥2 的 part 里有音符未带 <staff>（严重）
  N4b 谱表编号越界 —— <staff> 值超出声明的 staves（严重）
  N4c staves 未声明 —— 音符带 <staff> 而该 part 未声明 staves（轻）

输出：标准体检卡（规则ID 严重度 小节 详情），与 theory_check 卡并列成册。

用法:
    python3 notation_check.py <文件.musicxml>
    python3 notation_check.py <文件> --json 结果.json
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from collections import OrderedDict

FINDINGS = []   # (sev, code, measure, desc)


def add(sev, code, measure, desc):
    FINDINGS.append((sev, code, measure, desc))


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


def _beam_unit_quarters(beats, beat_type):
    """同一口径：一个连杠组的时间宽度（四分音符数）。4/4 → 1.0；6/8 → 1.5。"""
    unit = 4.0 / beat_type
    if beat_type == 8 and beats % 3 == 0:
        unit *= 3
    return unit


def _num(x):
    """小节号数值化（用于排序）；非纯数字原样返回。"""
    s = str(x)
    return int(s) if s.isdigit() else s


def _collect(part):
    """一个 part 的小节→(事件序列, div, unit_q, 小节拍号)。

    事件：('note', e) / ('break',)；e 含 onset/dur/rest/voice/staff/type/dots/
    beam1/stem。和弦成员不入序列（随主音符）。
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
            if tag in ('backup', 'forward'):
                pos += (float(_findtext(el, 'duration') or 0) *
                        (-1 if tag == 'backup' else 1))
                seq.append(('break', None))
            elif tag == 'note':
                if _find(el, 'chord') is not None:
                    continue
                if _find(el, 'grace') is not None:
                    seq.append(('break', None))
                    continue
                dur = float(_findtext(el, 'duration') or 0)
                b1 = None
                for b in [c for c in el if _t(c) == 'beam']:
                    if (b.get('number') or '1') == '1':
                        b1 = (b.text or '').strip()
                e = dict(onset=pos, dur=dur,
                         rest=(_find(el, 'rest') is not None),
                         voice=(_findtext(el, 'voice') or '1'),
                         staff=(_findtext(el, 'staff')),
                         type=(_findtext(el, 'type') or ''),
                         dots=len([c for c in el if _t(c) == 'dot']),
                         tup=(_find(el, 'time-modification') is not None),
                         beam1=b1,
                         stem=(_findtext(el, 'stem') or '').strip() or None)
                seq.append(('note', e))
                pos += dur
        out.append((_num(meas.get('number') or str(len(out) + 1)), seq, div,
                    _beam_unit_quarters(beats, beat_type),
                    dict(beats=beats, beat_type=beat_type, div=div)))
    return out


def _expected_groups(seq, div, unit_q):
    """按拍分组期望（与 notation_fix 同一口径，独立实现）。"""
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


def _xml_chains(seq):
    """从 XML 中回收符杠链：[(chain_events, complete)] 与孤儿链标记。"""
    chains, orphans = [], []
    cur = None
    for kind, e in seq:
        if kind == 'break' or (kind == 'note' and e['rest']):
            if cur:
                orphans.append(cur)
                cur = None
            continue
        b = e['beam1']
        if b == 'begin':
            if cur:
                orphans.append(cur)
            cur = [e]
        elif b in ('continue', 'end'):
            if cur is None:
                orphans.append([e])          # 无 begin 的续/尾
            else:
                cur.append(e)
                if b == 'end':
                    chains.append(cur)
                    cur = None
        else:
            if cur:
                orphans.append(cur)
                cur = None
    if cur:
        orphans.append(cur)
    return chains, orphans


def check_part(part, part_index, staves_declared, part_name):
    # 声乐谱识别：XML 层查 <lyric> 标签（按字分杠属合法）——N1a 对声乐谱不适用（2026-10-10 修）
    try:
        has_lyrics = any('lyric' in (el.tag if isinstance(el.tag, str) else '')
                         for el in part.iter())
    except AttributeError:
        has_lyrics = False
    for mno, seq, div, unit_q, ts in _collect(part):
        expected = _expected_groups(seq, div, unit_q)
        exp_keys = {tuple(round(e['onset'], 4) for e in g) for g in expected}

        # ── N1a 符杠缺失（严重）──────────────────────────────
        # 判据：期望组内各音的 onset 须落在同一条符杠链里（组内被连住即可；
        # 连成了跨拍长链属分组问题，归 N1b 轻项，不重复报严重）
        chains, orphans = _xml_chains(seq)
        # 修复（2026-10-10，二级流行歌件实录误报）：原链索引键＝(onset) 跨声部互踩——
        # RH 与 LH 在同一 onset 各起一条链时，后入者覆盖先入者，另一声部的期望组必然
        # "找不到自己的链"而报假阳性 N1a（双 staff 件、LH 含八分链时必炸）。键改 (voice, staff, onset)。
        def _ev_key(e):
            return (e['voice'], e['staff'], round(e['onset'], 4))
        onset_chain = {}
        for c in chains:
            for e in c:
                onset_chain[_ev_key(e)] = c
        for g in expected:
            ck = onset_chain.get(_ev_key(g[0])) if g else None
            ck_keys = {_ev_key(e) for e in ck} if ck else set()
            if not all(_ev_key(e) in ck_keys for e in g):
                if has_lyrics:
                    continue   # 声乐谱按字分杠合法，不报（已在卡脚注声明）
                beat = int((g[0]['onset'] / div) // unit_q) + 1
                ons = '、'.join(f"{e['onset'] / div:.2f}" for e in g)
                add('严重', 'N1a', mno,
                    f"第{beat}拍 {len(g)} 音（{g[0]['type']}）未连符杠，on 拍位 {ons}")

        # ── N1b 符杠分组不符（轻）────────────────────────────
        for c in chains:
            key = tuple(round(e['onset'], 4) for e in c)
            if key not in exp_keys:
                add('轻', 'N1b', mno,
                    f"符杠链 {len(c)} 音（on {c[0]['onset'] / div:.2f} 起）与按拍分组不符")
        for c in orphans:
            add('轻', 'N1b', mno,
                f"符杠链残缺/孤立（on {c[0]['onset'] / div:.2f} 起，{len(c)} 音）")

        # ── N2a 符干不齐（严重）／标注不齐（轻）──────────────
        for c in chains:
            stems = [e['stem'] for e in c]
            present = [s for s in stems if s in ('up', 'down')]
            if len(set(present)) >= 2:
                add('严重', 'N2a', mno,
                    f"符杠链内符干方向不一致：{present}（on {c[0]['onset'] / div:.2f} 起）")
            elif 0 < len(present) < len(stems):
                add('轻', 'N2a', mno,
                    f"符杠链内符干标注不齐（{len(present)}/{len(stems)} 有标注）")

        # ── N3 休止符布局（轻）────────────────────────────────
        beats, beat_type = ts['beats'], ts['beat_type']
        bar_ql = beats * 4.0 / beat_type
        if beat_type == 4:
            allowed_half = {0.0}
            if beats == 4:
                allowed_half = {0.0, 2.0}
            elif beats == 6:
                allowed_half = {0.0, 3.0}
            for kind, e in seq:
                if kind != 'note' or not e['rest']:
                    continue
                ql = e['dur'] / div
                if e['type'] == 'half' and e['dots'] == 0:
                    if round(e['onset'] / div, 4) not in allowed_half:
                        add('轻', 'N3a', mno,
                            f"二分休止符起于 {e['onset'] / div:.2f} 拍（4/4 应起于第 1 或第 3 拍）")
                if e['type'] == 'whole':
                    if abs(e['onset']) > 1e-6 or abs(ql - bar_ql) > 1e-6:
                        add('轻', 'N3b', mno,
                            f"全休止符起于 {e['onset'] / div:.2f} 拍、总长 {ql}（应起于小节首、满整小节）")
        # N3c 拍内休止未合并：某一拍恰由 ≥2 个休止符连排填满（应合并书写）
        if beat_type == 4:
            units = int(round(bar_ql / unit_q))
            rests = [e for kind, e in seq if kind == 'note' and e['rest']]
            for k in range(units):
                lo, hi = k * unit_q * div, (k + 1) * unit_q * div
                inside = sorted([e for e in rests
                                 if e['onset'] >= lo - 1e-6 and e['onset'] + e['dur'] <= hi + 1e-6],
                                key=lambda e: e['onset'])
                if len(inside) < 2:
                    continue
                fill = (abs(inside[0]['onset'] - lo) < 1e-6
                        and abs(inside[-1]['onset'] + inside[-1]['dur'] - hi) < 1e-6
                        and all(abs(inside[i]['onset'] + inside[i]['dur']
                                    - inside[i + 1]['onset']) < 1e-6
                                for i in range(len(inside) - 1))
                        and len({(e['voice'], e['staff']) for e in inside}) == 1)
                if fill:
                    add('轻', 'N3c', mno,
                        f"第{k + 1}拍由 {len(inside)} 个休止符填满，宜合并书写")


def check_staves_declared(part):
    """该 part 声明的 staves 值（第一处 attributes 为准）；无声明返回 None。"""
    for meas in [c for c in part if _t(c) == 'measure']:
        for a in [c for c in meas if _t(c) == 'attributes']:
            s = _findtext(a, 'staves')
            if s:
                return int(float(s))
    return None


def check_staff_assign(part, staves_declared):
    """N4 谱表分配：逐 <note>（含和弦成员）检查 staff 标记（严重项）。"""
    saw_staff_no_decl = False
    for meas in [c for c in part if _t(c) == 'measure']:
        mno = _num(meas.get('number') or '?')
        for el in [c for c in meas if _t(c) == 'note']:
            st = _findtext(el, 'staff')
            if staves_declared and staves_declared >= 2 and st is None:
                add('严重', 'N4a', mno,
                    f"part 声明 staves={staves_declared}，有 note 未带 <staff>（渲染归属不明）")
            if staves_declared and st is not None and int(st) > staves_declared:
                add('严重', 'N4b', mno, f"<staff>{st}</staff> 超出声明 staves={staves_declared}")
            if staves_declared is None and st is not None:
                saw_staff_no_decl = True
    if saw_staff_no_decl:
        add('轻', 'N4c', _first_measure_number(part),
            "音符带 <staff> 标记但该 part 未声明 staves（多数渲染器可容忍，[?] 按规范应补）")


def _first_measure_number(part):
    for c in part:
        if _t(c) == 'measure':
            return _num(c.get('number') or '?')
    return '?'


def check_convention(part, part_index, staves_declared, part_name):
    """N2b：钢琴双谱表／RH-LH 命名的符干方向约定（轻）。"""
    name = (part_name or '').lower()
    up_keys = ('rh', 'right', '高', 'treble', 'melody')
    down_keys = ('lh', 'left', '低', 'bass')
    mode = None
    if staves_declared and staves_declared >= 2:
        mode = 'by-staff'
    elif any(k in name for k in down_keys):
        mode = 'down'
    elif any(k in name for k in up_keys):
        mode = 'up'
    if mode is None:
        return
    bad, first = 0, None
    for mno, seq, div, unit_q, ts in _collect(part):
        for kind, e in seq:
            if kind != 'note' or e['rest'] or e['stem'] not in ('up', 'down'):
                continue
            want = None
            if mode == 'by-staff' and e['staff'] is not None:
                want = 'up' if int(e['staff']) <= 1 else 'down'
            elif mode in ('up', 'down'):
                want = mode
            if want and e['stem'] != want:
                bad += 1
                if first is None:
                    first = (mno, e['onset'] / div, e['stem'], want)
    if bad:
        label = part_name or f'P{part_index + 1}'
        std = 'staff1 向上／staff2 向下' if mode == 'by-staff' else mode
        add('轻', 'N2b', first[0],
            f"{label} 共 {bad} 处符干方向偏离约定（{std}），"
            f"首处 on {first[1]:.2f} 拍 为 {first[2]}（应为 {first[3]}）")


def build_report(source, label=None):
    """source：文件路径或 bytes。返回 (文本卡, findings)。"""
    FINDINGS.clear()
    if isinstance(source, bytes):
        root = ET.fromstring(source)
        name = label or '<bytes>'
    else:
        root = ET.parse(source).getroot()
        name = label or os.path.basename(source)
    parts = [c for c in root if _t(c) == 'part']
    for pi, part in enumerate(parts):
        # part 名（part-list → score-part id → part-name）
        pname = None
        pl = _find(root, 'part-list')
        if pl is not None:
            sps = [c for c in pl if _t(c) == 'score-part']
            if pi < len(sps):
                pname = _findtext(sps[pi], 'part-name')
        pname = pname or f'P{pi + 1}'
        sd = check_staves_declared(part)
        check_part(part, pi, sd, pname)
        check_staff_assign(part, sd)
        check_convention(part, pi, sd, pname)

    code_names = {'N1a': '符杠缺失', 'N1b': '符杠分组不符', 'N2a': '符干方向',
                  'N2b': '符干约定', 'N3a': '二分休止越拍', 'N3b': '全休止位置',
                  'N3c': '拍内休止未合并', 'N4a': '谱表归属缺失', 'N4b': '谱表编号越界',
                  'N4c': 'staves 未声明'}
    order = {'严重': 0, '轻': 1}
    findings = sorted(FINDINGS, key=lambda f: (order.get(f[0], 9), f[2], f[1]))
    lines = [f'═══ 记谱规范体检卡 — {name} ═══']
    hard = [f for f in findings if f[0] == '严重']
    soft = [f for f in findings if f[0] == '轻']
    lines.append(f'严重 {len(hard)} 处｜轻 {len(soft)} 处')
    lines.append('')
    if not findings:
        lines.append('干净：符杠分组、符干方向、休止符布局、谱表分配均未见违规')
    for sev, code, mno, desc in findings:
        lines.append(f'  [{sev}] {code} {code_names.get(code, "")} m{mno}: {desc}')
    lines.append('')
    lines.append('口径：严重＝违反通用记谱规范（人无需再看）／轻＝约定与风格偏差（人可裁）')
    lines.append('注：N1a 面向器乐谱；声乐谱（含歌词者自动识别）按字分杠合法，已跳过不报（2026-10-10 实测验修）')
    lines.append('注：复拍子按附点单位分组；本器实测覆盖 4/4，其余拍号与十六分次级符杠规则标 [?]')
    lines.append('注：N2b 只对钢琴双谱表与 RH/LH 命名谱生效，其余谱不判符干约定')
    return '\n'.join(lines), findings


def main():
    ap = argparse.ArgumentParser(description='记谱规范检器（符杠／符干／休止符布局／谱表分配）')
    ap.add_argument('file', help='MusicXML')
    ap.add_argument('--json', help='结果写 JSON')
    args = ap.parse_args()
    text, findings = build_report(args.file)
    print(text)
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump([{'sev': s, 'code': c, 'measure': m, 'desc': d}
                       for s, c, m, d in findings], f, ensure_ascii=False, indent=1)
        print(f'（JSON 已写 {args.json}）')


if __name__ == '__main__':
    main()
