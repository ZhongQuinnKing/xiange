#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归用例：玉尺·谱引擎壳（yuchi_score_check）探针与边界。

五场景：①干净谱（全绿）；②小节时值错（W3a）；③附点四分错位（W1a）；
④连音线悬置（W2）；⑤变音记号重复（W5a）。另验 CLI 契约（缺文件拒收 rc=2）。
判据：规则按设计触发、干净谱零误报。

跑法：python3 test_yuchi_score_check.py
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
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1">
'''

CLEAN = HEAD + '''    <measure number="1">
      <attributes><divisions>2</divisions><key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef></attributes>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>2</duration><type>quarter</type></note>
      <note><pitch><step>D</step><octave>5</octave></pitch><duration>2</duration><type>quarter</type></note>
      <note><pitch><step>E</step><octave>5</octave></pitch><duration>2</duration><type>quarter</type></note>
      <note><pitch><step>F</step><octave>5</octave></pitch><duration>2</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>
'''

SHORT_BAR = HEAD + '''    <measure number="1">
      <attributes><divisions>2</divisions><key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>2</duration><type>quarter</type></note>
      <note><pitch><step>D</step><octave>5</octave></pitch><duration>2</duration><type>quarter</type></note>
      <note><pitch><step>E</step><octave>5</octave></pitch><duration>2</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>
'''

DOT_OFF = HEAD + '''    <measure number="1">
      <attributes><divisions>2</divisions><key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>2</duration><type>quarter</type></note>
      <note><pitch><step>D</step><octave>5</octave></pitch><duration>1</duration><type>eighth</type></note>
      <note><pitch><step>E</step><octave>5</octave></pitch><duration>6</duration><dot/><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>
'''

SYNCOPATION = HEAD + '''    <measure number="1">
      <attributes><divisions>2</divisions><key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>2</duration><type>quarter</type></note>
      <note><pitch><step>D</step><octave>5</octave></pitch><duration>1</duration><type>eighth</type></note>
      <note><pitch><step>E</step><octave>5</octave></pitch><duration>3</duration><dot/><type>quarter</type></note>
      <note><pitch><step>F</step><octave>5</octave></pitch><duration>2</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>
'''

TIE_DANGLING = HEAD + '''    <measure number="1">
      <attributes><divisions>2</divisions><key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><type>half</type>
        <tie type="start"/></note>
      <note><pitch><step>D</step><octave>5</octave></pitch><duration>4</duration><type>half</type></note>
    </measure>
  </part>
</score-partwise>
'''

ACCIDENTAL_REPEAT = HEAD + '''    <measure number="1">
      <attributes><divisions>2</divisions><key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>F</step><alter>1</alter><octave>5</octave></pitch><duration>2</duration><type>quarter</type></note>
      <note><pitch><step>F</step><alter>1</alter><octave>5</octave></pitch><duration>2</duration><type>quarter</type></note>
      <note><pitch><step>G</step><octave>5</octave></pitch><duration>4</duration><type>half</type></note>
    </measure>
  </part>
</score-partwise>
'''

fails = []


def run(*args):
    r = subprocess.run([sys.executable, os.path.join(TOOLS, 'yuchi_score_check.py'), *args],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def check(name, cond, detail=''):
    if cond:
        print(f'  ✓ {name}')
    else:
        fails.append(f'{name} {detail}')
        print(f'  ✗ {name} {detail}')


def main():
    with tempfile.TemporaryDirectory() as td:
        cases = {
            'clean': CLEAN, 'short': SHORT_BAR, 'dotoff': DOT_OFF,
            'tie': TIE_DANGLING, 'acc': ACCIDENTAL_REPEAT,
            'sync': SYNCOPATION,
        }
        paths = {}
        for k, v in cases.items():
            paths[k] = os.path.join(td, f'{k}.musicxml')
            open(paths[k], 'w', encoding='utf-8').write(v)

        print('① 干净谱：零误报')
        rc, out = run(paths['clean'])
        check('rc=0', rc == 0, f'rc={rc}')
        check('无判罚', '未发现规范层问题' in out, out[:200])

        print('② 小节时值错：W3a')
        rc, out = run(paths['short'])
        check('W3a 触发', 'W3a' in out, out[:200])
        check('无串报', all(c not in out for c in ('W1a', 'W2', 'W5a')), out[:300])

        print('③ 附点四分越出小节：W1a')
        rc, out = run(paths['dotoff'])
        check('W1a 触发', 'W1a' in out, out[:200])
        check('无串报', all(c not in out for c in ('W2', 'W5a')), out[:300])

        print('③b 合法切分（附点四分压拍、尾落拍线）：零误报')
        rc, out = run(paths['sync'])
        check('无判罚', '未发现规范层问题' in out, out[:200])

        print('④ 连音线悬置：W2')
        rc, out = run(paths['tie'])
        check('W2 触发', 'W2' in out, out[:200])

        print('⑤ 变音记号重复：W5a')
        rc, out = run(paths['acc'])
        check('W5a 触发', 'W5a' in out, out[:200])

        print('⑥ CLI 契约：缺文件 rc=2')
        rc, out = run(os.path.join(td, 'nope.musicxml'))
        check('rc=2 且报读谱失败', rc == 2 and '读谱失败' in out, f'rc={rc} {out[:120]}')

    if fails:
        print(f'\n失败 {len(fails)} 项：')
        for f in fails:
            print(' -', f)
        return 1
    print('\n全过。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
