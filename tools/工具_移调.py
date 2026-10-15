#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具_移调.py —— MusicXML 整体移调（任意调，秒级）。

用法:
  python3 工具_移调.py <输入.musicxml> <目标调[±N]> [输出名]
  目标调写法:C G D A E B F# F Bb Eb Ab Db Gb
  可带显式位移:Ab-4（下 4 半音）、Ab+8 等；不带时默认最小位移（±6 半音内），
  方向差 12 半音即差一个八度。
机制:读源 <fifths> 自动算移调量（五度圈换算）；文本级手术——
     只动 pitch（step/alter/octave）与 fifths 两类，其余字节不动。
     支持紧凑式与多行式两种 <pitch> 写法；多行式输入处理后 pitch 段
     归为紧凑写法，段外字节仍不动。
记名:按目标调侧记名（降号调→降号系 Eb/Ab/Bb；升号调→升号系 C#/F#；C 调随源侧）。
附:音数守恒断言；移调前后音域对比打印（供与歌者音域比对）。
拒收面（前置检测，均给明确语，不留 traceback）:
  无 <fifths>：报「源文件未找到 <fifths>，无法自动判源调；未做任何改动」。
  有 <pitch> 但无一可解析：报数量与提示，未做任何改动。
场景:歌者音域不同→迅速移调（声乐伴奏/教材场景核心工具）。
"""
import os
import re
import sys

BASE = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
NAMES_S = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
NAMES_F = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']
FIFTHS = {'C': 0, 'G': 1, 'D': 2, 'A': 3, 'E': 4, 'B': 5, 'F#': 6,
          'F': -1, 'Bb': -2, 'Eb': -3, 'Ab': -4, 'Db': -5, 'Gb': -6}
PITCH_RE = re.compile(
    r'<pitch>\s*<step>([A-G])</step>\s*'
    r'(?:<alter>\s*(-?\d+)\s*</alter>\s*)?'
    r'<octave>\s*(\d+)\s*</octave>\s*</pitch>')


def midi_of(s, a, o):
    return BASE[s] + a + (o + 1) * 12


def range_line(tag, matches, side_names):
    ps = [midi_of(mo.group(1), int(mo.group(2) or 0), int(mo.group(3)))
          for mo in matches]
    lo, hi = min(ps), max(ps)

    def f(p):
        return f'{side_names[p % 12]}{p // 12 - 1}'

    return f'  {tag}音域：{f(lo)}–{f(hi)}（MIDI {lo}–{hi}）'


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    src, tgt_raw = sys.argv[1], sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else None
    m_t = re.fullmatch(r'([A-G][b#]?)([+-]\d+)?', tgt_raw)
    tgt = m_t.group(1) if m_t else None
    shift = int(m_t.group(2)) if m_t and m_t.group(2) else None
    if tgt not in FIFTHS:
        print(f'目标调不支持：{tgt_raw}（可选：{" ".join(FIFTHS)}，可带位移如 Ab-4）')
        sys.exit(1)
    txt = open(src, encoding='utf-8').read()
    m = re.search(r'<fifths>(-?\d+)</fifths>', txt)
    if not m:
        print('源文件未找到 <fifths>，无法自动判源调；未做任何改动')
        sys.exit(1)
    matches = list(PITCH_RE.finditer(txt))
    n_pitch_tags = txt.count('<pitch>')
    if n_pitch_tags and not matches:
        print(f'检出 {n_pitch_tags} 个 <pitch>，但无一可解析（不在支持面：'
              f'step/alter/octave 结构或写法异常）；未做任何改动')
        sys.exit(1)
    if not matches:
        print('源文件未见 <pitch> 音符内容；未做任何改动')
        sys.exit(1)
    src_f, tgt_f = int(m.group(1)), FIFTHS[tgt]
    m12 = ((tgt_f - src_f) * 7) % 12              # circle-of-fifths steps -> semitones (0-11)
    if shift is None:
        n = m12 if m12 <= 6 else m12 - 12         # minimal displacement (tritone rounds up)
    else:
        if (shift - m12) % 12:
            print(f'位移 {shift:+d} 与目标调 {tgt} 不符'
                  f'（应为 {m12} 或 {m12 - 12}，及与之相差 12 倍数的值）')
            sys.exit(1)
        n = shift
    if n == 0 and src_f == tgt_f:
        print(f'源调与目标调相同（fifths {src_f}→{tgt_f}），无移调动作')
        sys.exit(0)

    flat_side = tgt_f < 0 or (tgt_f == 0 and src_f < 0)   # flat/sharp side decides the spelling system
    use = NAMES_F if flat_side else NAMES_S

    def sub_note(mo):
        mid = midi_of(mo.group(1), int(mo.group(2) or 0), int(mo.group(3))) + n
        nm = use[mid % 12]
        step = nm[0]
        alt = 1 if nm.endswith('#') else (-1 if nm.endswith('b') else 0)
        al = f'<alter>{alt}</alter>' if alt else ''
        return f'<pitch><step>{step}</step>{al}<octave>{mid // 12 - 1}</octave></pitch>'

    new = PITCH_RE.sub(sub_note, txt)
    new = re.sub(r'<fifths>-?\d+</fifths>', f'<fifths>{tgt_f}</fifths>', new)

    assert txt.count('<pitch>') == new.count('<pitch>'), '音数守恒断言失败'
    if out is None:
        stem, ext = os.path.splitext(src)
        out = f'{stem}_{tgt}调{ext}'
    with open(out, 'w', encoding='utf-8') as f:
        f.write(new)
    if n == 0:
        desc = '等音改写（音高不动，仅换记名与调号）'
    else:
        desc = f'{"上" if n > 0 else "下"} {abs(n)} 半音'
    print(f'✓ 已移调：{os.path.basename(src)} → {tgt} 调（{desc}，'
          f'{"降号系" if flat_side else "升号系"}记名），音数守恒通过')
    print(range_line('原谱', matches, NAMES_F if src_f < 0 else NAMES_S))
    print(range_line('新谱', list(PITCH_RE.finditer(new)), use))
    print(f'  输出：{out}')


if __name__ == '__main__':
    main()
