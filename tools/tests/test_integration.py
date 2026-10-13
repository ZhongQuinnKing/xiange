#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""集成样例：6 小节端到端小样本走三道工序检器（批二 D三·3.2）。

样本：C 大调两手小曲，旋律四分／二分，低音全音符（避开需符杠的八分与休止布局，
作为工序链下限样例）。判定：记谱关、乐理关、体检三件 rc=0 且无严重项。
跑法：python3 test_integration.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)

HEAD = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Piano</part-name></score-part>
    <score-part id="P2"><part-name>Piano</part-name></score-part>
  </part-list>
  <part id="P1">
'''
MEL = [('E5', 'D5', 'C5'), ('F5', 'E5', 'D5'), ('G5', 'F5', 'E5'),
       ('A5', 'G5', 'F5'), ('G5', 'F5', 'E5'), ('D5', 'C5', 'E5')]
BASS = ['C3', 'D3', 'E3', 'F3', 'E3', 'C3']


def note(s, d, t):
    return (f'      <note><pitch><step>{s[0]}</step><octave>{s[1]}</octave>'
            f'</pitch><duration>{d}</duration><type>{t}</type></note>\n')


def build_fixture():
    p1 = ''
    for i, (a, b, c) in enumerate(MEL, 1):
        p1 += f'    <measure number="{i}">\n'
        if i == 1:
            p1 += ('      <attributes><divisions>2</divisions><key><fifths>0</fifths></key>'
                   '<time><beats>4</beats><beat-type>4</beat-type></time>'
                   '<clef><sign>G</sign><line>2</line></clef></attributes>\n')
        p1 += note(a, 2, 'quarter') + note(b, 2, 'quarter') + note(c, 4, 'half')
        p1 += '    </measure>\n'
    p1 += '  </part>\n'
    p2 = '  <part id="P2">\n'
    for i, s in enumerate(BASS, 1):
        p2 += f'    <measure number="{i}">\n'
        if i == 1:
            p2 += ('      <attributes><divisions>2</divisions><key><fifths>0</fifths></key>'
                   '<time><beats>4</beats><beat-type>4</beat-type></time>'
                   '<clef><sign>F</sign><line>4</line></clef></attributes>\n')
        p2 += note(s, 8, 'whole')
        p2 += '    </measure>\n'
    p2 += '  </part>\n</score-partwise>\n'
    return HEAD + p1 + p2


fails = []


def run(script, *args):
    r = subprocess.run([sys.executable, os.path.join(TOOLS, script), *args],
                       capture_output=True, text=True, timeout=180)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def main():
    with tempfile.TemporaryDirectory() as td:
        fx = os.path.join(td, 'six_bars.musicxml')
        open(fx, 'w', encoding='utf-8').write(build_fixture())

        rc, out = run('notation_check.py', fx)
        if rc != 0 or '严重 0 处' not in out:
            fails.append(f'记谱关未过 rc={rc}: {out[:150]}')

        rc, out = run('theory_check.py', fx)
        if rc != 0 or '严重 0 处' not in out:
            fails.append(f'乐理关未过 rc={rc}: {out[:150]}')

        rc, out = run('score_doctor.py', 'inspect', fx)
        if rc != 0 or '未发现明显异常' not in out:
            fails.append(f'体检未过 rc={rc}: {out[:150]}')

    if fails:
        print('用例失败：')
        for f in fails:
            print('  -', f)
        return 1
    print('用例通过：6 小节小样过三道检器（记谱／乐理／体检）全绿')
    return 0


if __name__ == '__main__':
    sys.exit(main())
