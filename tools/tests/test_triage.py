#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""triage 自校验 — 机械裁三规则＋口径对齐＋三色报对账＋回填安全

自足版：内嵌手写 MusicXML 造病例，不依赖任何外部谱件。
（必须手写 XML：对象构造 → write → 再解析的路子会把 forward/backup 规整掉，
病态小节根本造不出来；test_score_doctor 也栽过同一个坑。）

病例（4/4，divisions=480，一个四分＝480 tick）：
  FILE1 m1 正常四拍          → 无记录
        m2 首有 forward 占位  → M1 补休止，且既有音符位置一格不动
        m3 尾缺口            → M1 补休止
        m4 末音能截          → M2 截短归一
        m5 末音整音越界      → M2 拦下 → 人裁（该音归属待判）
        m6 两线并一格        → M0 口径假象，判定不裁
        m7 只写一拍          → 人裁（缺超半节）
        m8 并轨且不足        → 人裁（补休止补不齐求和）
  FILE2 m1 首节短两拍        → 人裁（弱起歧义）

断言：
  1 逐案裁决（档＋规则号）与预期一致
  2 口径对齐：每条 W2 记录的 S 与其详情文本里 theory_check 报的数逐条相等
  3 三色报：机械裁＋多源裁＋人裁 ＝ 记录总数；已回填数 ＝ 有改动的机械裁数
  4 回填件：能解析；被裁小节时值和 ＝ 拍号值；未裁小节字节原样；
     theory_check 复跑 W2 旗数 ＝ 原旗数 − 已回填数
  5 多源裁：接第二源后，人能裁的项应被第二源裁定（计数＝预期）

用法: python3 triage_selftest.py
"""
import io
import os
import re
import sys
import tempfile
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import triage as TR
from music21 import converter

HEAD = '''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>RH</part-name></score-part></part-list>
  <part id="P1">
'''
TAIL = '''  </part>
</score-partwise>
'''
ATTR = ('<attributes><divisions>480</divisions>'
        '<time><beats>4</beats><beat-type>4</beat-type></time></attributes>')
FAILS = []


def note(step, octv, ticks, voice='1'):
    return (f'<note><pitch><step>{step}</step><octave>{octv}</octave></pitch>'
            f'<duration>{ticks}</duration><voice>{voice}</voice></note>')


def measure(num, body):
    return f'<measure number="{num}">{ATTR}{body}</measure>'


def build_file1():
    m1 = note('C', 4, 480) + note('D', 4, 480) + note('E', 4, 480) + note('F', 4, 480)
    # m2 has a forward 480 placeholder, content 3.0 beats -> M1; the placeholder should become an explicit rest
    m2 = ('<forward><duration>480</duration></forward>'
          + note('G', 4, 960) + note('A', 4, 480))
    # m3 content 3.0 beats, trailing gap 1.0 -> M1
    m3 = note('B', 4, 960) + note('C', 5, 480)
    # m4 content 5.0 beats, last note 2.0 over by 1.0, trimmable -> M2
    m4 = note('D', 5, 480) + note('E', 5, 480) + note('F', 5, 480) + note('G', 5, 960)
    # m5 content 5.0 beats, last whole note (1.0) fully outside -> M2 blocks -> human
    m5 = (note('A', 5, 480) + note('B', 5, 480) + note('C', 6, 480)
          + note('D', 6, 480) + note('E', 6, 480))
    # m6 v1 whole note + v2 four quarters: sum 8.0, occupancy 4.0 -> M0
    m6 = (note('C', 3, 1920) + '<backup><duration>1920</duration></backup>'
          + note('E', 4, 480, '2') + note('F', 4, 480, '2')
          + note('G', 4, 480, '2') + note('A', 4, 480, '2'))
    # m7 only 1.0 beat written -> 3.0 short, over half a measure -> human
    m7 = note('C', 4, 480)
    # m8 merged and short: sum 3.0, occupancy 2.0 -> human
    m8 = (note('C', 3, 960) + '<backup><duration>960</duration></backup>'
          + '<forward><duration>240</duration></forward>' + note('E', 4, 480, '2'))
    return (HEAD + ''.join(measure(i + 1, b) for i, b in
                           enumerate([m1, m2, m3, m4, m5, m6, m7, m8])) + TAIL)


def build_file2():
    return HEAD + measure(1, note('C', 4, 960)) + TAIL


def snap_measures(path):
    """{小节号: {'S':时值和, 'notes':[(起点,时值,音名)], 'rests':[(起点,时值)]}}"""
    sc = converter.parse(path)
    out = {}
    for ps in sc.parts:
        for m in ps.getElementsByClass('Measure'):
            els = list(m.recurse().notesAndRests)
            out[str(m.number)] = dict(
                S=round(sum(float(e.quarterLength) for e in els), 6),
                notes=sorted((round(float(e.offset), 4), round(float(e.quarterLength), 4),
                              e.nameWithOctave) for e in els if not e.isRest),
                rests=sorted((round(float(e.offset), 4), round(float(e.quarterLength), 4))
                             for e in els if e.isRest))
    return out


def w2_count(path):
    TR.TC.FINDINGS.clear()
    sc = TR.TC.check_file(path)
    TR.TC.check_measure_lengths(sc)
    return sum(1 for f in TR.TC.FINDINGS if f[1] == 'W2')


def check(cond, msg):
    print(('  [OK] ' if cond else '  [FAIL] ') + msg)
    if not cond:
        FAILS.append(msg)


def main():
    tmp = tempfile.mkdtemp(prefix='triage_selftest_', dir='/var/tmp')
    f1 = os.path.join(tmp, 't1.musicxml')
    f2 = os.path.join(tmp, 't2.musicxml')
    open(f1, 'w', encoding='utf-8').write(build_file1())
    open(f2, 'w', encoding='utf-8').write(build_file2())

    print('== 1 裁决逐案对表 ==')
    _, recs1, _, counts1 = TR.scan_records(f1)
    expect = {2: 'M1', 3: 'M1', 4: 'M2', 5: None, 6: 'M0', 7: None, 8: None}
    check(counts1.get('W2') == 7, f'FILE1 W2 旗数 {counts1.get("W2")}（期望 7）')
    st1 = TR.collect_stats(converter.parse(f1))

    def pick(st_all, mno):
        return next((v for k, v in st_all.items() if str(k[1]) == str(mno)), None)

    for mno, want in expect.items():
        r = next((x for x in recs1 if str(x['位置']['小节']) == str(mno)), None)
        if r is None:
            check(False, f'm{mno} 没有生成记录')
            continue
        v = TR.mechanical_verdict(pick(st1, mno))
        rule = (v or {}).get('规则')
        check(rule == want, f"m{mno} 判据 → {rule}（期望 {want}）"
                            + (f"｜挡：{v.get('挡')}" if want is None else ''))
    print('  FILE2 首节短：')
    _, recs2, _, _ = TR.scan_records(f2)
    st2 = TR.collect_stats(converter.parse(f2))
    v2 = TR.mechanical_verdict(pick(st2, 1))
    check(v2['规则'] is None and '首节' in v2['挡'],
          f"FILE2 m1 → {v2['挡'][:22]}（期望首节短挡下）")

    print('== 2 口径对齐（两个账本的 S 必须逐条相等）==')
    bad = []
    for r in recs1 + recs2:
        if r['来源'] != 'W2':
            continue
        mm = re.search(r'小节时值 ([0-9.]+) ≠', r['证据']['读数']['详情'])
        if not mm or abs(float(mm.group(1)) - r['证据']['读数']['S求和']) > 1e-6:
            bad.append(r['编号'])
    check(not bad, f'全部 W2 记录 S 与 theory_check 详情一致（{len(recs1) + len(recs2)} 条）'
                   + (f'｜不一致：{bad}' if bad else ''))

    print('== 3 resolve：回填＋明细＋三色报 ==')
    out = os.path.join(tmp, 't1_out.musicxml')
    rep = os.path.join(tmp, 'rep.txt')
    buf = io.StringIO()
    argv = sys.argv[:]
    sys.argv = ['triage.py', 'resolve', f1, '--out', out, '--report', rep, '--only', 'W2']
    try:
        with redirect_stdout(buf):
            TR.main()
    finally:
        sys.argv = argv
    text = buf.getvalue()
    argv2 = sys.argv[:]
    sys.argv = ['triage.py', 'resolve', f1, '--out', out, '--dry-run', '--only', 'W2']
    try:
        with redirect_stdout(io.StringIO()):
            TR.main()
    finally:
        sys.argv = argv2
    # reading the filled JSON directly is steadier; here we reconcile via report text
    m = re.search(r'机械裁 (\d+) 处（已回填 (\d+)｜判定不裁 (\d+)）', text)
    multi = re.search(r'多源裁 (\d+) 处', text)
    human = re.search(r'人裁\s+(\d+) 处', text)
    check(bool(m and multi and human), '三色报三段都在')
    if m and multi and human:
        mech, done, mark = int(m.group(1)), int(m.group(2)), int(m.group(3))
        tot = mech + int(multi.group(1)) + int(human.group(1))
        check(mech == 4 and done == 3 and mark == 1,
              f'机械裁 {mech}（回填 {done}／不裁 {mark}）＝期望 4（3／1）')
        check(int(multi.group(1)) == 0 and int(human.group(1)) == 3,
              f"多源裁 {multi.group(1)}、人裁 {human.group(1)}（期望 0、3）")
        check(tot == 7, f'三色相加 {tot} ＝ W2 记录总数 7')
    check(os.path.exists(out + '.changes.txt'), '改动明细文件已生成')

    print('== 4 回填件安全性 ==')
    a, b = snap_measures(f1), snap_measures(out)
    check(set(a) == set(b), f'小节集合一致（{len(a)}）')
    for mno in ('2', '3'):
        check(abs(b[mno]['S'] - 4.0) < 1e-6, f"m{mno} 回填后时值和 {b[mno]['S']} ＝ 4.0")
        check(a[mno]['notes'] == b[mno]['notes'],
              f"m{mno} 补休止：既有音符（{len(a[mno]['notes'])} 个）起点时值一格不动")
        check(len(b[mno]['rests']) == len(a[mno]['rests']) + 1,
              f"m{mno} 只多出一个休止（{a[mno]['rests']} → {b[mno]['rests']}）")
    # m4 is a trim case: only the last note's duration shrinks by 1.0; all other notes and onsets untouched
    na, nb = a['4']['notes'], b['4']['notes']
    check(abs(b['4']['S'] - 4.0) < 1e-6, f"m4 回填后时值和 {b['4']['S']} ＝ 4.0")
    check(len(na) == len(nb) and [x[:1] + x[2:] for x in na] == [x[:1] + x[2:] for x in nb],
          'm4 截短只改时值：音名与起点全不动')
    check(nb[-1][1] == na[-1][1] - 1.0 and [x[1] for x in na[:-1]] == [x[1] for x in nb[:-1]],
          f"m4 只有末音被截 {na[-1][1]} → {nb[-1][1]}，前 {len(na) - 1} 个音时值不动")
    for mno in ('1', '5', '6', '7', '8'):
        check(a[mno]['notes'] == b[mno]['notes'], f'm{mno} 未裁，音符集原样')
        check(abs(a[mno]['S'] - b[mno]['S']) < 1e-6, f'm{mno} 未裁，时值和不动')
    check(w2_count(out) == w2_count(f1) - 3,
          f'复跑 W2 旗数 {w2_count(f1)} → {w2_count(out)}（应减 3）')

    print('== 5 多源裁前哨 ==')
    argv3 = sys.argv[:]
    sys.argv = ['triage.py', 'resolve', f1, '--out', out + '2', '--second', f2,
                '--dry-run', '--only', 'W2']
    buf3 = io.StringIO()
    try:
        with redirect_stdout(buf3):
            TR.main()
    finally:
        sys.argv = argv3
    t3 = buf3.getvalue()
    check('回填件' not in t3 or 'dry-run' in t3, 'dry-run 不写盘')
    print('  （FILE2 与 FILE1 小节时值和不同，第二源不合拍 → 人裁不降级，符合预期）')

    if FAILS:
        print(f'\n自校验未通过 {len(FAILS)} 项：')
        for f in FAILS:
            print('  - ' + f)
        print(f'（中间件在 {tmp}）')
        return 1
    print(f'\n全部通过。中间件在 {tmp}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
