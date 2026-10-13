#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""score_doctor 自校验 — 重叠判据与 fix 安全网

自足版：内嵌手写 XML 构造病例，不依赖任何外部文件。
（必须手写 XML：对象构造 → write → 再解析的路径会把重叠规整掉，
用它造"真重叠件"会假过；含 backup 元素的手写 XML 才保得住重叠。）

病例：
  1 跨小节相接（每小节 4 个四分音）→ 0 处重叠（局部坐标混排曾误报 4 处）
  2 小节内真重叠（全音符横跨四分音起点）→ 报 1 处
  3 fix 真重叠件 → 截短 1 处、修后收敛、.orig 备份 + .changes.txt 明细齐
  4 fix 无重叠件 → 0 截短、不出去重叠明细（旧版跨小节误截 21 处）
  5-7 CLI 契约：缺参／inspect 缺文件／fix 缺文件 → rc=2 干净报错（2026-10-13 统一）

用法: python3 test_score_doctor.py
"""
import io
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import score_doctor
from score_doctor import parts_of, find_overlaps

from music21 import converter

HEAD = '''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="4.0">
  <part-list>
    <score-part id="P1"><part-name>T1</part-name></score-part>
  </part-list>
  <part id="P1">
'''
TAIL = '''  </part>
</score-partwise>
'''
ATTRS = ('      <attributes><divisions>4</divisions><key><fifths>0</fifths></key>'
         '<time><beats>4</beats><beat-type>4</beat-type></time>'
         '<clef><sign>G</sign><line>2</line></clef></attributes>\n')


def note_xml(step, octv, dur, typ='quarter'):
    return (f'      <note><pitch><step>{step}</step><octave>{octv}</octave></pitch>'
            f'<duration>{dur}</duration><voice>1</voice><type>{typ}</type></note>\n')


def x_no_overlap():
    """两小节各 4 个四分音——跨小节处局部坐标会与全局错位"""
    m1 = ''.join(note_xml(s, o, 4) for s, o in [('C', 4), ('D', 4), ('E', 4), ('F', 4)])
    m2 = ''.join(note_xml(s, o, 4) for s, o in [('G', 4), ('A', 4), ('B', 4), ('C', 5)])
    return (HEAD + '    <measure number="1">\n' + ATTRS + m1 + '    </measure>\n'
            + '    <measure number="2">\n' + m2 + '    </measure>\n' + TAIL)


def x_true_overlap():
    """C4 全音符(0→4) + backup 回 1.0 处放 E4 四分(1→2) → 真重叠 1 处"""
    m1 = (note_xml('C', 4, 16, 'whole')
          + '      <backup><duration>12</duration></backup>\n'
          + note_xml('E', 4, 4)
          + '      <forward><duration>8</duration></forward>\n')
    m2 = note_xml('G', 4, 16, 'whole')
    return (HEAD + '    <measure number="1">\n' + ATTRS + m1 + '    </measure>\n'
            + '    <measure number="2">\n' + m2 + '    </measure>\n' + TAIL)


def write_tmp(dirpath, name, content):
    p = os.path.join(dirpath, name)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(content)
    return p


def count_overlaps(path):
    sc = converter.parse(path)
    return sum(len(find_overlaps(items)) for items in parts_of(sc).values())


def main():
    passed, failed = [], []

    def check(name, cond, detail):
        (passed if cond else failed).append(name)
        print(f'{"✓" if cond else "✗"} {name}: {detail}')

    tmp = tempfile.mkdtemp(prefix='scd_selftest_')
    try:
        p1 = write_tmp(tmp, 'no_overlap.musicxml', x_no_overlap())
        p2 = write_tmp(tmp, 'true_overlap.musicxml', x_true_overlap())

        # 1 跨小节相接不误报
        n1 = count_overlaps(p1)
        check('跨小节相接 0 误报', n1 == 0, f'报出 {n1} 处（期望 0）')

        # 2 真重叠被捉
        n2 = count_overlaps(p2)
        check('小节内真重叠被捉', n2 == 1, f'报出 {n2} 处（期望 1）')

        # 3 fix 真重叠件：备份 + 明细 + 截短收敛
        out = os.path.join(tmp, 'fixed.musicxml')
        with redirect_stdout(io.StringIO()):
            score_doctor.fix(p2, out)
        bak_p = p2 + '.orig'
        log_p = out + '.changes.txt'
        ok_bak = os.path.exists(bak_p) and open(bak_p, encoding='utf-8').read() == open(p2, encoding='utf-8').read()
        ok_log = os.path.exists(log_p) and '[去重叠]' in open(log_p, encoding='utf-8').read()
        ok_conv = count_overlaps(out) == 0
        check('fix 真重叠：备份+明细+收敛', ok_bak and ok_log and ok_conv,
              f'备份={ok_bak} 明细={ok_log} 收敛={ok_conv}')

        # 4 fix 无重叠件：0 截短（不许出 [去重叠] 明细；旧版跨小节误截）
        out2 = os.path.join(tmp, 'fixed2.musicxml')
        with redirect_stdout(io.StringIO()):
            score_doctor.fix(p1, out2)
        log2 = out2 + '.changes.txt'
        no_trim = (not os.path.exists(log2)) or ('[去重叠]' not in open(log2, encoding='utf-8').read())
        check('fix 无重叠件 0 截短', no_trim,
              '明细文件=' + ('无' if not os.path.exists(log2) else '有且无去重叠条目'))

        # 5-7 CLI 契约：缺参／缺文件每路 rc=2 干净报错（2026-10-13 统一）
        import subprocess
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'score_doctor.py')
        nope = os.path.join(tmp, 'nope.musicxml')

        r = subprocess.run([sys.executable, script], capture_output=True, text=True, timeout=120)
        check('CLI 缺参 rc=2', r.returncode == 2 and '用法' in (r.stdout + r.stderr),
              f'rc={r.returncode}')

        r = subprocess.run([sys.executable, script, 'inspect', nope],
                           capture_output=True, text=True, timeout=120)
        check('CLI inspect 缺文件 rc=2', r.returncode == 2 and '读谱失败' in (r.stdout + r.stderr)
              and 'Traceback' not in (r.stdout + r.stderr), f'rc={r.returncode}')

        r = subprocess.run([sys.executable, script, 'fix', nope, os.path.join(tmp, 'o.musicxml')],
                           capture_output=True, text=True, timeout=120)
        check('CLI fix 缺文件 rc=2', r.returncode == 2 and '读谱失败' in (r.stdout + r.stderr)
              and 'Traceback' not in (r.stdout + r.stderr), f'rc={r.returncode}')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failed:
        print(f'✗✗ {len(failed)} 病例不过：{failed}')
        sys.exit(1)
    print(f'✓✓ 七病例全过（{len(passed)}/7）— 重叠判据与 fix 安全网、CLI 契约正确')


if __name__ == '__main__':
    main()
