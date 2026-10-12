#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
triage — 待裁闭环第一期（发现环＋机械裁＋三色报）

设计依据：待裁闭环设计件（2026-10-10 夜立）。
第一期只做三件：待裁记录格式（定稿）＋ W2 时值类机械裁 ＋ 三色报；不依赖新引擎。

＝ 待裁记录格式（定稿 v1，JSON 的键就是格式）＝

  编号   规则号-小节-声部（同处多条加括号序，如 E4-m10-LH（2））
  位置   页/行/小节/拍。（MusicXML 输入没有版面信息，页与行记 null 并标 [?]；
         键盘谱加"声部"一项，左右手分开记账）
  类型   共识分歧 / 低置信 / 乐理可疑（本期只产出"乐理可疑"）
  来源   规则号：W2 小节时值 / W1 声部重叠 / E1..E4 严重级
  严重度 严重 / 轻
  证据   各引擎读数（含口径）＋ 图面坐标（本期为 null＝尚未接版面）
  建议   机器给出的人裁建议（做什么、为什么挡着）
  裁决   档（待定/机械裁/多源裁/人裁）＋规则＋动作＋改动明细

＝ 口径（跟现有工具对齐，不另立一套）＝

  S 求和  Σ 小节内全部音符与休止的 quarterLength —— theory_check W2 的原口径，机械裁沿用同一条
  U 占用  小节内时值区间的并集时长（并轨去重）—— 辅助读数，只用于判"虚警"，不替换 W2 判据
  P 越界  小节内最大 (offset+duration) − 拍号值
  E 目标  拍号一小节时值（theory_check 的 expect）

  为什么要有 U：一个 part 里并了两条声部（骨架转写的常事）时，S 会把重叠部分算两遍，
  W2 报警而小节其实合拍。m10 LH 就是这种（S=5.0，U=4.0）。这类记 M0 判"口径假象"。

＝ 机械裁规则（只在这三条里定，条条留痕）＝

  M0 口径假象  |U − E| ≤ 0.005 → 内容其实合拍 → 判定不裁（不动谱面，理由入账）
  M1 补休止    S = U < E、无越界、非首节、缺量 ≤ E/2 → 在缺口处补休止至合拍
  M2 尾部截短  S > E 且越界量够吸收全部超出、且不把任何音削没 → 截尾至合拍
  三条都不中 → 人裁（待办）。给了 --second 第二源时，机械裁不中的先走多源裁：
  第二源同位置合拍（S2 ≈ E）→ 采信"按拍号归一"；第二源也合不上 → 升级人裁。

  为什么把"补休止"排在"截短"前面当默认动作：补是加，不改任何既有音符；
  截是改，风险高，只在"内容确实写过了小节线"这一种情形下动，且必列明细。

＝ 回填只走外科式 XML 补丁 ＝

  music21 的 write 在本批数据上会重排节奏、拆分音符（实测 B720 m5 LH 时值和 6.0→8.5），
  不能用来回填。本工具只动源 XML 的字符：补休止＝在缺口处插 <note><rest/></note>，
  截短＝改那一个音的 <duration>，其余字节原样。改完重新解析复检 S，闭合才算过。

用法:
    python3 triage.py scan    <文件.musicxml> [--json 清单.json] [--only W2]
    python3 triage.py resolve <文件.musicxml> --out <输出.musicxml>
                              [--second 第二源.musicxml] [--json 结果.json]
                              [--report 三色报.txt] [--dry-run] [--only W2]

输出：scan 出待裁清单；resolve 出回填件（不改输入）＋改动明细（<out>.changes.txt）＋三色报。
任何数字出库都带口径；核不准的标 [?]。
"""
import argparse
import json
import os
import re
import sys
from collections import OrderedDict

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import theory_check as TC          # W2 判据唯一实现处，本工具只引用不复制
from music21 import converter

TOL = 0.005        # 拍级容差（1/64 音符 = 0.0156 拍，取其三成）
MIN_TICK = 1       # 一个 duration 单位（divisions 粒度）

CODE_NAME = {'W2': '小节时值', 'W1': '声部重叠', 'E1': '声部交叉',
             'E2': '和弦音集', 'E3': '平行五八度', 'E4': '跨度过大'}


# ══════════════════════ 谱面统计（与 theory_check W2 同口径） ══════════════════════

def union_len(els):
    """时值区间并集时长（并轨去重）"""
    ivs = sorted((float(e.offset), float(e.offset) + float(e.quarterLength)) for e in els)
    u, cs, ce = 0.0, None, None
    for s, e in ivs:
        if ce is None or s > ce + 1e-9:
            if ce is not None:
                u += ce - cs
            cs, ce = s, e
        else:
            ce = max(ce, e)
    if ce is not None:
        u += ce - cs
    return u


def gaps_of(els, E, tol=TOL):
    """[0, E] 内未被内容盖住的区间（含首尾与内部空隙）"""
    ivs = sorted((float(e.offset), float(e.offset) + float(e.quarterLength)) for e in els)
    gaps, cur = [], 0.0
    for s, e in ivs:
        if s > cur + tol:
            gaps.append((cur, min(s, E)))
        cur = max(cur, e)
        if cur >= E - tol:
            break
    if cur < E - tol:
        gaps.append((cur, E))
    return [(a, b) for a, b in gaps if b - a > tol]


def collect_stats(score):
    """{(声部名, 小节号): {S,U,maxend,E,ts,is_first,mno,meas,part}}

    prev_ts 跨声部延续——与 theory_check.check_measure_lengths 的写法逐行对齐，
    口径一致才允许两边数字对账。
    """
    out = OrderedDict()
    prev_ts = None
    _seen = {}
    for ps in score.parts:
        name = ps.partName or ps.id
        # [本地适配 2026-10-11] 同名声部防键塌陷（out[(name, 小节)] 会互相覆盖）
        if str(name) in _seen:
            _seen[str(name)] += 1
            name = f'{name}#{_seen[str(name)]}'
        else:
            _seen[str(name)] = 1
        first = True
        for meas in ps.getElementsByClass('Measure'):
            els = list(meas.recurse().notesAndRests)
            ts = meas.timeSignature
            if ts is not None:
                prev_ts = ts
            else:
                ts = prev_ts
            st = dict(S=0.0, U=0.0, maxend=0.0, E=None, n=len(els), is_first=first,
                      ts=(ts.ratioString if ts is not None else None),
                      mno=meas.number, meas=meas, part=ps, part_name=name)
            if els:
                st['S'] = round(sum(float(e.quarterLength) for e in els), 6)
                st['U'] = round(union_len(els), 6)
                st['maxend'] = round(max(float(e.offset) + float(e.quarterLength)
                                         for e in els), 6)
            if ts is not None:
                st['E'] = float(ts.barDuration.quarterLength)
                st['spill'] = sorted(
                    [(round(float(e.offset), 6), round(float(e.quarterLength), 6),
                      round(float(e.offset) + float(e.quarterLength), 6))
                     for e in els
                     if float(e.offset) + float(e.quarterLength) > st['E'] + TOL],
                    key=lambda x: -x[2])
            out[(name, meas.number)] = st
            first = False
    return out


# ══════════════════════ 机械裁判据（纯函数，可单测） ══════════════════════

def mechanical_verdict(st):
    """给定小节统计 → 机械裁判定。

    返回 {'规则','动作','依据'}；不能机械裁时返回 {'规则': None, '挡': 原因}。
    """
    if st is None or st.get('E') is None:
        return {'规则': None, '挡': '缺拍号，判不了目标时值'}
    S, U, E, me = st['S'], st['U'], st['E'], st['maxend']
    if abs(U - E) <= TOL:
        return {'规则': 'M0', '动作': '不裁',
                '依据': f'占用 {U:g} 拍 = 拍号 {E:g} 拍（内容其实合拍）；'
                        f'求和 {S:g} 拍超系同声部并轨重复计数，判口径假象'}
    if S < E - TOL:
        if st['is_first']:
            return {'规则': None, '挡': '首节短，弱起与漏谱辨不开'}
        if (E - S) > E / 2 + TOL:
            return {'规则': None, '挡': f'缺 {E - S:g} 拍超半节，疑漏音而非漏休止'}
        if me > E + TOL:
            return {'规则': None, '挡': '有内容越出小节线，缺口补不回'}
        if abs(S - U) > TOL:
            return {'规则': None, '挡': f'并轨超计（S {S:g} ≠ U {U:g}），补休止补不齐求和'}
        return {'规则': 'M1', '动作': f'补休止 {round(E - S, 6):g} 拍',
                '依据': f'内容 {S:g} 拍不足 {E:g} 拍，无越界无并轨，于缺口处补休止归一'}
    if S > E + TOL:
        if me <= E + TOL:
            return {'规则': None, '挡': '超出不来自尾部越界（并轨或结构问题），截不到'}
        if (S - E) > (me - E) + TOL:
            return {'规则': None, '挡': f'越界量 {round(me - E, 6):g} 拍吸收不了全部超出 '
                                        f'{round(S - E, 6):g} 拍，余量在并轨处'}
        # 截得动吗：从最末音起，任一步会把某音削没就放手（削没＝归属问题，不是时值问题）
        need = S - E
        for off, dur, end in st.get('spill', []):
            if need <= TOL:
                break
            t = min(end - E, need)
            if dur - t <= TOL:
                return {'规则': None,
                        '挡': f'末音整音越出小节线（{off:g} 拍起、长 {dur:g} 拍），'
                              f'截短会把它削没——该音归属待判，机械裁不碰'}
            need -= t
        if need > TOL:
            return {'规则': None, '挡': '越界音截不完，余量不在尾部'}
        return {'规则': 'M2', '动作': f'截短末音共 {round(S - E, 6):g} 拍',
                '依据': f'内容越出小节线 {round(me - E, 6):g} 拍，可全数从末音截回拍号值'
                        f'（不削没任何音）'}
    return {'规则': None, '挡': '[?] 判据未覆盖的形态'}


# ══════════════════════ 清单（发现环） ══════════════════════

def part_of_desc(code, desc):
    """从 theory_check 的详情文本里取回声部名（W2 详情格式：'LH 小节时值 5.0 ≠ 拍号 4.0'）"""
    if code == 'W2':
        m = re.match(r'^(.*?) 小节时值 ', desc)
        return m.group(1) if m else None
    if code == 'W1':
        m = re.match(r'^(.*?) 交叠', desc)
        return m.group(1) if m else None
    if code == 'E4':
        m = re.match(r'^(.*?) 同拍跨度', desc)
        return m.group(1) if m else None
    if code == 'E5':
        m = re.match(r'^(.*?) 持续和弦', desc)
        return m.group(1) if m else None
    if code == 'E1':
        m = re.match(r'^(.*?)\(', desc)
        return m.group(1) if m else None
    if code == 'E3':
        m = re.match(r'^(.*?) 与 ', desc)
        return m.group(1) if m else None
    return None


def span_text(st):
    if st is None or st.get('E') is None:
        return '整节 [?]'
    E = st['E']
    if st['maxend'] > E + TOL:
        return f'{E:g}–{st["maxend"]:g} 拍（越界段）'
    if st['S'] < E - TOL:
        return f'0–{E:g} 拍（有内容 {st["S"]:g}）'
    return f'0–{E:g} 拍'


def advice_for(code, st, desc):
    if code == 'W2':
        v = mechanical_verdict(st)
        if v['规则']:
            return f"机械裁可定（{v['规则']}）：{v['依据']}"
        return f"人裁：{v['挡']}"
    if code == 'W1':
        return ('人裁：抽验该处（骨架一个声部里并了两条线时，重叠是转写所致，'
                '不是真错；确认后按并轨拆声部或放行）')
    if code == 'E4':
        return '人裁：同拍跨度过大超默认可及，钢琴上难够到——改转位或分解，或确认为八度误判'
    if code == 'E3':
        return '人裁：平行五八度，流行织体里可能是有意的（听感判断；[?] 本卡不裁艺术）'
    if code == 'E1':
        return '人裁：声部交叉，确认是不是左右手写串了'
    return f'人裁：[?] {CODE_NAME.get(code, code)} 未有既定处置口径'


def build_record(code, sev, mno, desc, part, st, path, seen):
    key = f'{code}-m{mno}-{part or "?"}'
    seen[key] = seen.get(key, 0) + 1
    rid = key if seen[key] == 1 else f'{key}（{seen[key]}）'
    ev = OrderedDict()
    ev['引擎'] = os.path.basename(path)
    ev['读数'] = OrderedDict()
    if st is not None and st.get('E') is not None:
        ev['读数'].update([
            ('S求和', st['S']), ('U占用', st['U']),
            ('越界', round(st['maxend'] - st['E'], 6)),
            ('E目标', st['E']), ('拍号', st['ts'])])
        ev['口径'] = 'W2 求和法（Σ 小节内音符与休止时值，与 theory_check 同口径）'
    else:
        ev['口径'] = f'theory_check {code}（{CODE_NAME.get(code, "")}）'
    ev['读数']['详情'] = desc
    ev['图面坐标'] = None
    rec = OrderedDict([
        ('编号', rid),
        ('位置', OrderedDict([('页', None), ('行', None),
                              ('小节', mno), ('声部', part), ('拍', span_text(st))])),
        ('类型', '乐理可疑'),
        ('来源', code),
        ('严重度', sev),
        ('证据', ev),
        ('建议', advice_for(code, st, desc)),
        ('裁决', OrderedDict([('档', '待定'), ('规则', None), ('动作', None), ('改动', [])])),
    ])
    return rec


def scan_records(path, only=None):
    """发现环：跑 theory_check（唯一口径源）→ 待裁记录。

    返回 (score, records, stats, counts)；解析失败返回 (None, None, None, None)。
    counts 是全量发现（不受 --only 影响）的底账，三色报要用它对账。
    """
    TC.FINDINGS.clear()
    score = TC.check_file(path)
    if score is None:
        return None, None, None, None
    TC.check_measure_lengths(score)
    findings = list(TC.FINDINGS)
    counts = OrderedDict()
    counts['严重'] = sum(1 for f in findings if f[0] == '严重')
    counts['轻'] = sum(1 for f in findings if f[0] == '轻')
    for f in findings:
        counts[f[1]] = counts.get(f[1], 0) + 1
    stats = collect_stats(score)
    seen = OrderedDict()
    records = []
    for sev, code, mno, desc in findings:
        if only and code not in only:
            continue
        part = part_of_desc(code, desc)
        st = stats.get((part, mno)) if part else None
        records.append(build_record(code, sev, mno, desc, part, st, path, seen))
    return score, records, stats, counts


# ══════════════════════ 外科式 XML 补丁 ══════════════════════

ELEM_RE = re.compile(r'<(note|backup|forward|attributes|direction|barline|print|sound|harmony)\b')


def _tag_end(body, start, tag):
    gt = body.index('>', start)
    if body[gt - 1] == '/':
        return gt + 1
    return body.index('</%s>' % tag, start) + len(tag) + 3


def parse_elements(body):
    """小节体 → 顶层元素序列 [{'tag','start','end','text'}]（字符偏移，供精确拼接）"""
    elems, last_end = [], -1
    for m in ELEM_RE.finditer(body):
        start = m.start()
        if start < last_end:
            continue                      # 落在上一个元素内部，丢弃
        end = _tag_end(body, start, m.group(1))
        elems.append({'tag': m.group(1), 'start': start, 'end': end,
                      'text': body[start:end]})
        last_end = end
    return elems


def _dur_of(text):
    m = re.search(r'<duration>(\d+)</duration>', text)
    return int(m.group(1)) if m else None


def _voice_of(text):
    m = re.search(r'<voice>([^<]*)</voice>', text)
    return m.group(1) if m else '1'


class MeasureXML:
    """小节体的时间线游标（chord 成员不推进游标——与 music21 读法一致）"""

    def __init__(self, body, div):
        self.body, self.div = body, div
        self.elems = parse_elements(body)
        cur, head = 0, None
        for e in self.elems:
            e['cur_in'] = cur
            t = e['text']
            if e['tag'] == 'backup':
                cur -= (_dur_of(t) or 0)
            elif e['tag'] == 'forward':
                cur += (_dur_of(t) or 0)
            elif e['tag'] == 'note':
                d = _dur_of(t) or 0
                e['dur'] = d
                if '<chord' in t and head is not None:
                    e['off'] = head
                else:
                    e['off'] = cur
                    head = cur
                    cur += d
                e['voice'] = _voice_of(t)
                e['is_rest'] = '<rest' in t
            e['cur_out'] = cur

    def notes(self):
        return [e for e in self.elems if e['tag'] == 'note']


def plan_rests(mx, gaps_q):
    """缺口 → 插入休止的字符级改动 [(pos_start, pos_end, 片段, 说明)]

    关键安全点：非尾缺口后面若有 forward 占位（骨架件里空缺常写成 forward），
    补休止必须把它吃掉——否则休止占时间、forward 再占一遍，整节音符整体后移，
    小节反而更糟（实测踩过一次）。找不到占位符就不猜，回 None 交人裁。
    """
    div, out = mx.div, []
    for a, b in gaps_q:
        a_t, b_t = int(round(a * div)), int(round(b * div))
        d = b_t - a_t
        if d < MIN_TICK:
            continue
        idx, voice = None, None
        for i, e in enumerate(mx.elems):
            if e['cur_out'] <= a_t + 1:
                idx = i
            if e['tag'] == 'note' and voice is None and e['off'] >= a_t - 1:
                voice = e['voice']
        if voice is None:
            voice = next((e['voice'] for e in mx.notes() if 'voice' in e), '1')
        frag = f'<note><rest/><duration>{d}</duration><voice>{voice}</voice></note>'
        nxt = None
        for j in range((idx + 1) if idx is not None else 0, len(mx.elems)):
            if mx.elems[j]['tag'] in ('note', 'forward'):
                nxt = mx.elems[j]
                break
        if nxt is None:                       # 尾缺口：后面没东西，落节尾，位置安全
            pos = mx.elems[-1]['end'] if mx.elems else 0
            out.append((pos, pos, frag,
                        f'补休止 {d}/{div} 拍 voice{voice} 于 {a:g} 拍处（缺口 {a:g}–{b:g}，节尾）'))
            continue
        if nxt['tag'] == 'forward' and (_dur_of(nxt['text']) or 0) >= d:
            fd = _dur_of(nxt['text']) or 0
            left = fd - d
            repl = frag if left < MIN_TICK else (
                frag + f'<forward><duration>{left}</duration></forward>')
            out.append((nxt['start'], nxt['end'], repl,
                        f'补休止 {d}/{div} 拍 voice{voice} 于 {a:g} 拍处（缺口 {a:g}–{b:g}；'
                        f'把该处 {fd} tick 的 forward 占位显式化成休止，音符位置不动）'))
            continue
        return None                           # 缺口既非尾部也无 forward 占位：不猜
    return out


def plan_trims(mx, E_q, need_q):
    """越界音 → 改 duration 的字符级改动；不安全返回 (None, 原因)"""
    div = mx.div
    E_t, need = int(round(E_q * div)), int(round(need_q * div))
    heads = []
    els = mx.elems
    for i, e in enumerate(els):
        if e['tag'] != 'note' or e['is_rest']:
            continue
        if '<chord' in e['text']:
            continue                      # 和弦成员不单独截，随头处理
        heads.append(e)
    spill = sorted([e for e in heads if e['off'] + e['dur'] > E_t + 1],
                   key=lambda e: -(e['off'] + e['dur']))
    out, r = [], need
    for e in spill:
        if r <= 1:
            break
        avail = e['off'] + e['dur'] - E_t
        t = min(avail, r)
        newdur = e['dur'] - t
        if newdur < MIN_TICK:
            return None, f'截短会把 {e["off"]}/{div:g} 拍处的音削没（需截 {t} tick）'
        m = re.search(r'<duration>\d+</duration>', e['text'])
        if not m:
            return None, '目标音找不到 duration 字段'
        new_text = e['text'][:m.start()] + f'<duration>{newdur}</duration>' + e['text'][m.end():]
        out.append((e['start'], e['end'], new_text,
                    f'截短 {e["off"]}/{div:g} 拍起该音 {e["dur"]}→{newdur} tick'
                    f'（截 {t}，越界收回小节线内）'))
        r -= t
    if r > 1:
        return None, f'只吸收得了 {need - r} tick，余 {r} tick 不在尾部'
    return out, None


class RawScore:
    """源 XML 的字符级定位（只读原字节，改动靠偏移拼接）"""

    def __init__(self, text):
        self.text = text
        m = re.search(r'<divisions>(\d+)</divisions>', text)
        self.div = int(m.group(1)) if m else 480
        self.part_ids = OrderedDict()
        for pid, nm in re.findall(
                r'<score-part id="([^"]+)"[^>]*>\s*<part-name>([^<]*)</part-name>', text):
            self.part_ids[nm] = pid

    def measure_body(self, part_name, mno):
        pid = self.part_ids.get(part_name)
        if pid is None:
            return None, None
        pm = re.search(r'<part id="%s">(.*?)</part>' % re.escape(pid), self.text, re.S)
        if not pm:
            return None, None
        pstart = pm.start(1)
        want = str(mno)
        for mm in re.finditer(r'<measure\b[^>]*\bnumber="([^"]+)"[^>]*>', pm.group(1)):
            if mm.group(1) == want:
                body_start = pstart + mm.end()
                body_end = pstart + pm.group(1).index('</measure>', mm.end())
                return body_start, body_end
        return None, None

    def measure_mxml(self, part_name, mno):
        bs, be = self.measure_body(part_name, mno)
        if bs is None:
            return None
        return MeasureXML(self.text[bs:be], self.div), bs


def apply_edits(text, edits):
    """edits = [(start, end, new_text)]，从后往前拼，其余字节原样"""
    for start, end, new in sorted(edits, key=lambda x: -x[0]):
        text = text[:start] + new + text[end:]
    return text


# ══════════════════════ 多源裁（第二期接口的轻量前哨） ══════════════════════

def second_stats(path):
    if not path or not os.path.exists(path):
        return None
    try:
        sc = converter.parse(path)
    except Exception:
        return None
    return collect_stats(sc)


def second_ok(ss, part, mno, E):
    """第二源该节合拍（±0.02 拍）→ True；第二源缺位返回 None"""
    if ss is None:
        return None
    st = ss.get((part, mno))
    if st is None or st.get('E') is None:
        return None
    return abs(st['S'] - E) <= 0.02


# ══════════════════════ 三色报 ══════════════════════

def three_color_text(path, records, tail_lines=None):
    m = OrderedDict()
    for r in records:
        m[r['裁决']['档']] = m.get(r['裁决']['档'], 0) + 1
    mech_changed = sum(1 for r in records
                       if r['裁决']['档'] == '机械裁' and r['裁决']['改动'])
    mech_mark = m.get('机械裁', 0) - mech_changed
    codes = OrderedDict()
    for r in records:
        if r['裁决']['档'] in ('人裁', '待定'):
            codes[r['来源']] = codes.get(r['来源'], 0) + 1
    src = OrderedDict()
    for r in records:
        src[r['来源']] = src.get(r['来源'], 0) + 1
    L = []
    L.append(f'═══ 待裁三色报 — {os.path.basename(path)} ═══')
    L.append(f"待裁总数 {len(records)} 处｜" + '｜'.join(
        f'{CODE_NAME.get(c, c)} {n}' for c, n in src.items()))
    L.append(f"  机械裁 {m.get('机械裁', 0)} 处（已回填 {mech_changed}｜判定不裁 {mech_mark}）")
    L.append(f"  多源裁 {m.get('多源裁', 0)} 处")
    L.append(f"  人裁   {m.get('人裁', 0) + m.get('待定', 0)} 处（待办）"
             + (f"—— " + '｜'.join(f'{c} {n}' for c, n in codes.items()) if codes
                else ''))
    L.append('')
    for route in ('机械裁', '多源裁'):
        rs = [r for r in records if r['裁决']['档'] == route]
        if not rs:
            continue
        L.append(f'{route}明细：')
        for r in rs:
            L.append(f"  {r['编号']}（{r['位置']['小节']} 小节 {r['位置']['声部']}）"
                     f" {r['裁决']['规则']} → {r['裁决']['动作']}")
            for c in r['裁决']['改动']:
                L.append(f'      {c}')
        L.append('')
    if codes:
        L.append('人裁（待办）按来源：' + '｜'.join(f'{c} {n}' for c, n in codes.items()))
    if tail_lines:
        L.extend(tail_lines)
    return '\n'.join(L)


# ══════════════════════ scan ══════════════════════

def cmd_scan(args):
    score, records, stats, counts = scan_records(args.file, only=args.only)
    if records is None:
        print('解析失败：' + args.file)
        return 1
    m = OrderedDict()
    for r in records:
        m[r['类型']] = m.get(r['类型'], 0) + 1
    print(f'═══ 待裁清单 — {os.path.basename(args.file)} ═══')
    print('总数 %d 条（%s）｜未接：共识分歧、低置信（第二/三期）'
          % (len(records), '｜'.join(f'{k} {v}' for k, v in m.items())))
    print('全量发现底账：严重 %d｜轻 %d（W2 %d）%s'
          % (counts.get('严重', 0), counts.get('轻', 0), counts.get('W2', 0),
             '；--only 只筛本清单，底账不变' if args.only else ''))
    print('位置里的页/行＝null[?]：MusicXML 无版面信息，待裁卡（第三期）接图面坐标后回填')
    print('')
    for r in records:
        ev = r['证据']['读数']
        evtxt = (f"S={ev['S求和']} U={ev['U占用']} 越界={ev['越界']} E={ev['E目标']}"
                 if r['来源'] == 'W2' else str(ev.get('详情', ''))[:52])
        print(f"[{r['编号']}] m{r['位置']['小节']} {r['位置']['声部'] or '?'} "
              f"{r['来源']} {r['严重度']}｜{r['位置']['拍']}｜{evtxt}")
        print(f"    建议：{r['建议']}")
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=1)
        print(f'\n（清单已写 {args.json}）')
    return 0


# ══════════════════════ resolve ══════════════════════

def cmd_resolve(args):
    score, records, stats, counts = scan_records(args.file, only=args.only)
    if records is None:
        print('解析失败：' + args.file)
        return 1
    raw = open(args.file, encoding='utf-8').read()
    rs = RawScore(raw)
    ss = second_stats(args.second) if args.second else None
    if args.second:
        print(f'第二源：{os.path.basename(args.second)}'
              + ('' if ss is not None else '（解析失败，多源裁跳过 [?]）'))
    edits = []
    for r in records:
        code = r['来源']
        if code != 'W2':
            r['裁决'].update(档='人裁', 规则=None, 动作='非本期机械裁范围（' + code + '）')
            continue
        part, mno = r['位置']['声部'], r['位置']['小节']
        st = stats.get((part, mno))
        v = mechanical_verdict(st)
        if v['规则']:
            r['裁决'].update(档='机械裁', 规则=v['规则'], 动作=v['动作'])
            if v['规则'] in ('M1', 'M2'):
                mxres = rs.measure_mxml(part, mno)
                if mxres is None:
                    r['裁决'].update(档='人裁', 规则=None,
                                     动作='[?] 源 XML 里定位不到该小节，回填跳过')
                    continue
                mx, base = mxres
                if v['规则'] == 'M1':
                    ops = plan_rests(mx, gaps_of(list(st['meas'].recurse().notesAndRests),
                                                 st['E']))
                    if not ops:
                        r['裁决'].update(档='人裁', 规则='M1',
                                         动作='M1 拦下：缺口处没有 forward 占位可换，'
                                              '补休止会推走既有音符——交人裁')
                        continue
                    for s0, e0, frag, why in ops:
                        edits.append((base + s0, base + e0, frag))
                        r['裁决']['改动'].append(f'm{mno} {part}：{why}')
                else:  # M2
                    ops, why = plan_trims(mx, st['E'], st['S'] - st['E'])
                    if ops is None:
                        r['裁决'].update(档='人裁', 规则=None,
                                         动作=f'M2 拦下：[{why}]')
                        continue
                    for s0, e0, new, w in ops:
                        edits.append((base + s0, base + e0, new))
                        r['裁决']['改动'].append(f'm{mno} {part}：{w}')
            continue
        # 机械裁不定 → 多源裁（有第二源才启用）
        if ss is not None:
            ok = second_ok(ss, part, mno, st['E'] if st else 0)
            if ok:
                r['裁决'].update(档='多源裁', 规则='S1',
                                 动作='第二源该节合拍，采信"按拍号归一"；'
                                      '内容级回填属第二期，本期只记裁定')
                continue
            r['裁决'].update(档='人裁', 规则=None,
                             动作=f"人裁：{v['挡']}；第二源亦不合拍，升级人裁")
            continue
        r['裁决'].update(档='人裁', 规则=None, 动作=f"人裁：{v['挡']}")

    # 落盘
    changed = len(edits)
    out_path = args.out
    if changed and not args.dry_run:
        new_text = apply_edits(raw, edits)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(new_text)
        ch_path = out_path + '.changes.txt'
        with open(ch_path, 'w', encoding='utf-8') as f:
            for r in records:
                for c in r['裁决']['改动']:
                    f.write(c + '\n')
        print(f'回填件已写：{out_path}（字符级改动 {changed} 处，明细 {ch_path}）')
        print('输入件未改动（只读）。')
    elif changed and args.dry_run:
        print(f'[dry-run] 应回填 {changed} 处，未写盘。')
    else:
        print('无字符级改动，未写输出件（判定不裁的项已在三色报里入账）。')

    # 复检：输出件再跑一遍 theory_check
    tail = []
    if changed and not args.dry_run:
        TC.FINDINGS.clear()
        sc2 = TC.check_file(out_path)
        if sc2 is not None:
            TC.check_measure_lengths(sc2)
            f2 = list(TC.FINDINGS)
            e2 = [x for x in f2 if x[0] == '严重']
            w2 = [x for x in f2 if x[1] == 'W2']
            tail.append('')
            tail.append(f"复检（输出件跑 theory_check）：严重 {len(e2)}｜轻 {len(f2) - len(e2)}"
                        f"（W2 {len(w2)} 处）")
            tail.append(f"  原始件全量底账：严重 {counts.get('严重', 0)}｜"
                        f"轻 {counts.get('轻', 0)}（W2 {counts.get('W2', 0)} 处）")
            tail.append('  归一致消 %d 处（有改动）；口径假象 %d 处仍会报（非回归）；'
                        '其余待多源裁/人裁'
                        % (sum(1 for r in records if r['裁决']['档'] == '机械裁'
                               and r['裁决']['改动']),
                           sum(1 for r in records if r['裁决']['档'] == '机械裁'
                               and not r['裁决']['改动'])))
    tail.append('')
    tail.append('口径：W2 求和法（与 theory_check 同口径）；三色＝机械裁/多源裁/人裁；'
                '本报机判，改动逐条留痕')
    tail.append('第二源未接时，多源裁一列为 0——第二期接源级投票后启用（--second 为本期轻量前哨）')

    report = three_color_text(args.file, records, tail)
    print('')
    print(report)

    if args.report and not args.dry_run:
        with open(args.report, 'w', encoding='utf-8') as f:
            f.write(report + '\n')
        print(f'（三色报已写 {args.report}）')
    if args.json and not args.dry_run:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=1)
        print(f'（裁决清单已写 {args.json}）')
    return 0


def main():
    ap = argparse.ArgumentParser(description='待裁闭环第一期：发现环＋机械裁＋三色报')
    sub = ap.add_subparsers(dest='cmd', required=True)

    s1 = sub.add_parser('scan', help='生成待裁清单')
    s1.add_argument('file', help='MusicXML')
    s1.add_argument('--json', help='清单写 JSON')
    s1.add_argument('--only', nargs='+', help='只出指定规则号，如 --only W2')
    s1.set_defaults(func=cmd_scan)

    s2 = sub.add_parser('resolve', help='机械裁＋改动明细＋三色报')
    s2.add_argument('file', help='MusicXML（只读，不改动）')
    s2.add_argument('--out', help='回填件输出路径')
    s2.add_argument('--second', help='第二源 MusicXML（多源裁轻量前哨）')
    s2.add_argument('--json', help='裁决清单写 JSON')
    s2.add_argument('--report', help='三色报写文件')
    s2.add_argument('--dry-run', action='store_true', help='只算不写盘')
    s2.add_argument('--only', nargs='+', help='只处理指定规则号，如 --only W2')
    s2.set_defaults(func=cmd_resolve)

    args = ap.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
