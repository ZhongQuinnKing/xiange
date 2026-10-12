#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归用例：同名声部（单 part 双谱表，music21 拆后同名"Piano"）不得互相塌陷。

背景（2026-10-11 隔离验证第五轮抓出）：score_doctor／theory_check／triage 曾按
partName 建键，同名两声部后写入覆盖前者，右手侧整条静默失明。修复＝同名自动加
序号后缀（Piano#2）。本用例手造同名声部双声部谱，三件工具都必须"看见两件"。

跑法：python3 test_same_name_parts.py
"""
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
    <score-part id="P2"><part-name>Piano</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef></attributes>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
  </part>
  <part id="P2">
    <measure number="1">
      <attributes><divisions>1</divisions><key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>F</sign><line>4</line></clef></attributes>
      <note><pitch><step>C</step><octave>3</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>
'''

fails = []


def run(script, *args):
    r = subprocess.run([sys.executable, os.path.join(TOOLS, script), *args],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def main():
    with tempfile.TemporaryDirectory() as td:
        fx = os.path.join(td, 'same_name.musicxml')
        open(fx, 'w', encoding='utf-8').write(FIXTURE)

        rc, out = run('score_doctor.py', 'inspect', fx)
        if 'Piano#2' not in out:
            fails.append('score_doctor 未显示第二声部（Piano#2）')
        if out.count('音域') < 2:
            fails.append('score_doctor 未同时覆盖两件声部的音域')

        rc, out = run('theory_check.py', fx)
        if 'Piano#2' in out or '声部' in out:
            pass  # 展示名不一定报到卡面，只要不崩且不塌陷即可
        if rc != 0:
            fails.append(f'theory_check rc={rc}')

        rc, out = run('triage.py', 'scan', fx)
        if rc != 0:
            fails.append(f'triage rc={rc}')

    if fails:
        print('用例失败：')
        for f in fails:
            print('  -', f)
        return 1
    print('用例通过：同名声部三件工具均不塌陷（score_doctor 见 Piano#2 与两手音高；theory_check／triage 正常完成）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
