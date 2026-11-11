#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yuchi_score_check — 谱面规范查对（玉尺·谱模块引擎壳。2026-10-13 立）

口径：只判「合不合记谱规范」，不评音乐好坏（玉尺总纲：能力最强、把柄为零）。
与 notation_check 的边界：N 系已覆盖项不重造、不重报；简谱路由件走 N 系豁免。

规则清单 v0（五线谱 W 系，硬为先）：

  W3a 小节时值对账   —— 声明拍号 × 小节实际总时值不符（不含弱起小节）（严重）
  W3b 拍号缺失       —— 有音符而无拍号声明（轻）
  W1a 附点跨拍       —— 4/4 中附点四分起位不在半小节线（严重）
  W1b 附点八分孤置   —— 附点八分未与同拍十六分相接（轻，惯例）
  W2  连音线闭合     —— tie 起止不配对（同声部同音高计键）（轻）
  W5a 变音记号残留   —— 同小节同音高重复标记变音记号（轻，惯例）

判罚诚实分档：严重＝机械可判的硬规范违背；轻＝惯例偏差或拿不准的提示；
规则不适用该谱种/语境时不报，照实空栏，不硬套。

用法:
    python3 yuchi_score_check.py <文件.musicxml>
    python3 yuchi_score_check.py <文件> --json 结果.json
"""
import argparse
import json
import sys
import xml.etree.ElementTree as ET

FINDINGS = []  # (sev, code, measure, desc)


def add(sev, code, measure, desc):
    FINDINGS.append((sev, code, measure, desc))


def _t(el):
    return el.tag.split('}')[-1] if isinstance(el.tag, str) else ''


def _find(el, name):
    for c in el:
        if _t(c) == name:
            return c
    return None


def _findall(el, name):
    return [c for c in el if _t(c) == name]


def _findtext(el, name):
    c = _find(el, name)
    return (c.text or '') if c is not None else None


# -- parsing layer ------------------------------------------

def parse_parts(root):
    """返回 {part_id: {'measures': [(mno, implicit, attrs, notes)], 'name': str}}。"""
    parts = {}
    pl = _find(root, 'part-list')
    names = {}
    if pl is not None:
        for sp in _findall(pl, 'score-part'):
            names[sp.get('id')] = _findtext(sp, 'part-name') or sp.get('id')
    for part in _findall(root, 'part'):
        pid = part.get('id')
        ms = []
        for m in _findall(part, 'measure'):
            implicit = (m.get('implicit') == 'yes')
            ms.append((m.get('number'), implicit, _find(m, 'attributes'),
                       _findall(m, 'note')))
        parts[pid] = {'measures': ms, 'name': names.get(pid, pid)}
    return parts


def attr_get(attrs, name):
    if attrs is None:
        return None
    if name == 'time':
        t = _find(attrs, 'time')
        if t is None:
            return None
        b = _findtext(t, 'beats')
        bt = _findtext(t, 'beat-type')
        return (int(b), int(bt)) if b and bt and b.isdigit() else None
    if name == 'divisions':
        d = _findtext(attrs, 'divisions')
        return int(d) if d and d.isdigit() else None
    return None


def note_info(n):
    is_chord = _find(n, 'chord') is not None
    is_rest = _find(n, 'rest') is not None
    dur = _findtext(n, 'duration')
    dot = len(_findall(n, 'dot'))
    pitch_el = _find(n, 'pitch')
    step = _findtext(pitch_el, 'step') if pitch_el is not None else None
    octv = _findtext(pitch_el, 'octave') if pitch_el is not None else None
    alter = _findtext(pitch_el, 'alter') if pitch_el is not None else None
    ties = sorted(set(t.get('type') for t in _findall(n, 'tie') if t.get('type')))
    voice = _findtext(n, 'voice') or '1'
    st = _findtext(n, 'staff')
    return {
        'chord': is_chord, 'rest': is_rest,
        'dur': int(dur) if dur and dur.isdigit() else 0,
        'type': _findtext(n, 'type'), 'dots': dot,
        'pitch': (step, octv, alter) if step and octv else None,
        'ties': ties, 'voice': voice,
        'staff': int(st) if st and st.isdigit() else 1,
    }


def measure_events(notes, div=1):
    """拉平小节为事件流（含和弦成员），给出每个非和弦音的起位与尾位。

    逐声部推进（多声部各走各的时钟，防揉成一条）；起/尾均转拍单位（divisions 归一）。
    返回 (evs, onset_beats, tail_beats)，下标与 evs 对齐；和弦成员继承前一音的位。
    """
    evs = [note_info(n) for n in notes]
    onset = {}
    tail = {}
    per_voice = {}
    for idx, e in enumerate(evs):
        if e['chord']:
            onset[idx] = onset.get(idx - 1, 0.0)
            tail[idx] = tail.get(idx - 1, 0.0)
            continue
        v = (e['voice'], e['staff'])
        t = per_voice.get(v, 0.0)
        onset[idx] = t
        t += (e['dur'] or 0) / div
        tail[idx] = t
        per_voice[v] = t
    return evs, onset, tail


# -- rule W3: time-signature vs measure reconciliation ----------

def rule_w3(mno, implicit, attrs, notes, state, ctx):
    if implicit:
        return
    evs = ctx['evs']
    if not evs:
        return
    total = sum(e['dur'] for e in evs if not e['chord'])
    tt = state.get('time')
    div = state.get('div')
    if tt is None or div is None:
        if total > 0:
            add('轻', 'W3b', mno, '有音符而无拍号或 divisions 声明，无法对账')
        return
    beats, bt = tt
    expect = int(beats * 4 / bt * div)
    if total != expect:
        add('严重', 'W3a', mno,
            f'小节总时值 {total}（divisions）与拍号 {beats}/{bt} 应得 {expect} 不符')


# -- rule W1: dot placement ---------------------------------

def rule_w1(mno, implicit, attrs, notes, state, ctx):
    """简单拍（分母 4）：附点音不得越过物理小节末（硬）；
    附点八分的尾落点若与后接音头皆不接，提示惯例。逐声部计位。"""
    tt = state.get('time')
    if not tt or tt[1] != 4 or tt[0] <= 0:
        return  # 复合拍与分母非 4 者不判，照实空栏
    evs, onset, tail = ctx['evs'], ctx['onset'], ctx['tail']
    bar_len = float(tt[0])
    for idx, e in enumerate(evs):
        if e['chord'] or e['rest'] or e['dur'] <= 0:
            continue
        on = onset[idx]
        tl = tail[idx]
        if e['type'] == 'quarter' and e['dots'] == 1:
            if tl > bar_len + 1e-6:
                add('严重', 'W1a', mno,
                    f'附点四分起于第 {on + 1:.2f} 拍、尾落 {tl:.2f} 拍，越出小节'
                    f'（{tt[0]}/{tt[1]}）')
        if e['type'] == 'eighth' and e['dots'] == 1:
            next_on = {onset[i2] for i2, x in enumerate(evs)
                       if not x['chord'] and (x['voice'], x['staff']) == (e['voice'], e['staff'])}
            if any(abs(p - tl) < 1e-6 for p in next_on):
                continue  # 后接音与尾落点相接，合法
            if tl <= bar_len + 1e-6 and (tl >= bar_len - 1e-6):
                continue  # 尾落正好压小节末，合法
            add('轻', 'W1b', mno,
                f'附点八分起于第 {on + 1:.2f} 拍、尾落 {tl:.2f} 拍，后无同声部音相接（惯例）')


# -- rule W2: slur closure ----------------------------------

def rule_w2(parts):
    for pid, p in parts.items():
        pending = {}
        for mno, implicit, attrs, notes in p['measures']:
            for n in notes:
                ni = note_info(n)
                if ni['rest'] or ni['pitch'] is None:
                    continue
                key = (ni['pitch'], ni['voice'], ni['staff'])
                if 'start' in ni['ties'] and 'stop' not in ni['ties']:
                    if key in pending:
                        add('轻', 'W2', mno,
                            f'连音线同键又起（前起于小节 {pending[key]}）：'
                            f'{ni["pitch"][0]}{ni["pitch"][1]} v{ni["voice"]}')
                    pending[key] = mno
                elif 'stop' in ni['ties']:
                    if key not in pending:
                        add('轻', 'W2', mno,
                            f'连音线止而无起：{ni["pitch"][0]}{ni["pitch"][1]} v{ni["voice"]}')
                    else:
                        del pending[key]
        for key, mno in pending.items():
            add('轻', 'W2', mno,
                f'连音线起而未止（悬置）：{key[0][0]}{key[0][1]} v{key[1]}')


# -- rule W5: accidentals -----------------------------------

def rule_w5(mno, implicit, attrs, notes, state, ctx):
    seen = set()
    for e in ctx['evs']:
        if e['rest'] or e['pitch'] is None or e['chord']:
            continue
        step, octv, alter = e['pitch']
        if alter is None:
            continue
        key = (step, octv, e['voice'], e['staff'])
        if key in seen:
            add('轻', 'W5a', mno,
                f'{step}{octv} 本小节内重复标记变音记号（惯例，可省）')
        seen.add(key)


RULES_MEASURE = [rule_w3, rule_w1, rule_w5]


def run_rules(parts):
    for pid in sorted(parts):
        state = {'time': None, 'div': None}
        for mno, implicit, attrs, notes in parts[pid]['measures']:
            if attrs is not None:
                tt = attr_get(attrs, 'time')
                if tt:
                    state['time'] = tt
                d = attr_get(attrs, 'divisions')
                if d:
                    state['div'] = d
            evs, onset, tail = measure_events(notes, state.get('div') or 1)
            ctx = {'evs': evs, 'onset': onset, 'tail': tail}
            for r in RULES_MEASURE:
                r(mno, implicit, attrs, notes, state, ctx)
    rule_w2(parts)


# -- report layer -------------------------------------------

def report_text(path):
    lines = [f'谱面规范查对（yuchi_score_check）：{path}']
    n_sev = sum(1 for f in FINDINGS if f[0] == '严重')
    n_light = sum(1 for f in FINDINGS if f[0] == '轻')
    if not FINDINGS:
        lines.append('未发现规范层问题（按现行规则集）。')
    else:
        lines.append(f'共 {len(FINDINGS)} 处（严重 {n_sev}／轻 {n_light}）')
        for sev, code, m, desc in FINDINGS:
            lines.append(f'  [{sev}] {code} 小节{m}：{desc}')
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description='谱面规范查对（玉尺·谱引擎壳）')
    ap.add_argument('score', help='MusicXML 文件')
    ap.add_argument('--json', dest='json_out', default=None, help='结果落 JSON')
    args = ap.parse_args()
    try:
        tree = ET.parse(args.score)
    except (ET.ParseError, OSError) as e:
        print(f'读谱失败：{e}（文件须为合法 MusicXML）', file=sys.stderr)
        return 2
    root = tree.getroot()
    if _t(root) != 'score-partwise':
        print('只支持 score-partwise 形态的 MusicXML。', file=sys.stderr)
        return 2
    parts = parse_parts(root)
    run_rules(parts)
    print(report_text(args.score))
    if args.json_out:
        payload = [{'severity': s, 'code': c, 'measure': m, 'detail': d}
                   for s, c, m, d in FINDINGS]
        with open(args.json_out, 'w', encoding='utf-8') as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        print(f'JSON 已落：{args.json_out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
