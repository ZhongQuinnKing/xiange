#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归用例：记谱两件（notation_check 体检／notation_fix 修复）最小闭环与幂等。

背景（2026-10-11 隔离验证第五轮余件）：记谱两件此前无自测。本用例手造
「四个未连符杠的八分音符」器乐谱，验三事：①checker 能抓 N1a；②fixer 修复后复检归零；
③fixer 幂等（连跑两次字节不变）。

跑法：python3 test_notation.py
"""
import hashlib
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)

FIXTURE = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Piano</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>2</divisions><key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef></attributes>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>1</duration><type>eighth</type></note>
      <note><pitch><step>D</step><octave>5</octave></pitch><duration>1</duration><type>eighth</type></note>
      <note><pitch><step>E</step><octave>5</octave></pitch><duration>1</duration><type>eighth</type></note>
      <note><pitch><step>F</step><octave>5</octave></pitch><duration>1</duration><type>eighth</type></note>
      <note><pitch><step>G</step><octave>5</octave></pitch><duration>2</duration><type>quarter</type></note>
      <note><pitch><step>A</step><octave>5</octave></pitch><duration>2</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>
'''

fails = []


def run(script, *args):
    r = subprocess.run([sys.executable, os.path.join(TOOLS, script), *args],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def md5(p):
    return hashlib.md5(open(p, 'rb').read()).hexdigest()


def main():
    with tempfile.TemporaryDirectory() as td:
        fx = os.path.join(td, 'unbeamed.musicxml')
        open(fx, 'w', encoding='utf-8').write(FIXTURE)

        rc, out = run('notation_check.py', fx)
        if '[严重] N1a' not in out:
            fails.append('checker 未抓出 N1a 严重项（符杠缺失）')
        if rc == 0 and '严重 0 处' in out:
            fails.append('checker 对未连符杠样本报零严重')

        rc, out = run('notation_fix.py', fx)
        if rc != 0:
            fails.append(f'fixer rc={rc}')

        rc, out = run('notation_check.py', fx)
        if '[严重] N1a' in out or '严重 0 处' not in out:
            fails.append('修复后复检未归零（仍见 N1a 严重项）')

        h1 = md5(fx)
        run('notation_fix.py', fx)
        if md5(fx) != h1:
            fails.append('fixer 不幂等（二次跑字节变化）')

    if fails:
        print('用例失败：')
        for f in fails:
            print('  -', f)
        return 1
    print('用例通过：checker 抓 N1a → fixer 修复后归零 → 二次跑幂等')
    return 0


if __name__ == '__main__':
    sys.exit(main())
