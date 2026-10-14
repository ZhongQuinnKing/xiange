#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归用例：music_check 最小契约（知识库质检 rc 口径 0／1／2；环境口 MUSIC_CHECK_KB／OUT）。

断言：①库不存在 rc=2；②全过库 rc=0 且落 OUT 文件；③违规（破折号超配／混入字符）
rc=1 并逐条点名；④域文档缺 rc=1（引用被指向）。
跑法：python3 test_music_check.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
SCRIPT = os.path.join(TOOLS, 'music_check.py')

fails = []


def run(kb, out=None):
    env = dict(os.environ)
    env.pop('MUSIC_CHECK_KB', None)
    env.pop('MUSIC_CHECK_OUT', None)
    env['MUSIC_CHECK_KB'] = kb
    if out:
        env['MUSIC_CHECK_OUT'] = out
    r = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True,
                       timeout=120, env=env)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def make_kb(base, omit=None):
    files = {
        '10-乐理与记谱.md': '乐理与记谱笔记：音符、休止与拍号。',
        '20-和声.md': '和声笔记：阻碍终止的用法与听感。',
        '30-曲式.md': '曲式笔记：乐段与句法划分。',
        '40-复调.md': '复调笔记：对位与模仿。',
        '50-配器.md': '配器笔记：音色与音区安排。',
        '60-编配与即兴.md': '编配笔记：三层次织体的写法。',
        '70-风格体系.md': '风格笔记：五声性的用法。',
        '85-音乐史.md': '音乐史笔记：贝多芬的交响曲。',
        '87-音乐教育.md': '教育笔记：巴斯蒂安教程的进度。',
    }
    if omit:
        files.pop(omit)
    os.makedirs(base, exist_ok=True)
    for name, text in files.items():
        with open(os.path.join(base, name), 'w', encoding='utf-8') as fh:
            fh.write(text + '\n')
    return base


def main():
    # ① 库不存在 → rc=2
    rc, out = run('/nonexistent_kb_probe')
    if rc != 2 or '知识库目录不存在' not in out or 'Traceback' in out:
        fails.append(f'缺库未 rc=2 干净报错 rc={rc}: {out[-120:]}')

    with tempfile.TemporaryDirectory() as td:
        # ② 全过库 → rc=0 且落 OUT
        kb = make_kb(os.path.join(td, 'kb_ok'))
        report = os.path.join(td, 'report.md')
        rc, out = run(kb, report)
        if rc != 0 or '全部通过' not in out or 'Traceback' in out:
            fails.append(f'全过库未 rc=0 rc={rc}: {out[-160:]}')
        if not os.path.exists(report):
            fails.append('MUSIC_CHECK_OUT 未落盘')
        else:
            t = open(report, encoding='utf-8').read()
            if '# 知识库自动质检报告' not in t or '全部通过' not in t:
                fails.append(f'OUT 报告内容异常：{t[:120]}')

        # ③ 违规库 → rc=1 并点名两类问题
        kb_bad = make_kb(os.path.join(td, 'kb_bad'))
        with open(os.path.join(kb_bad, '99-杂.md'), 'w', encoding='utf-8') as fh:
            fh.write('一段话——中间——又来——第三处☃。\n')
        rc, out = run(kb_bad)
        if rc != 1 or '破折号' not in out or '混入字符' not in out or 'Traceback' in out:
            fails.append(f'违规未 rc=1 点名 rc={rc}: {out[-160:]}')

        # ④ 域文档缺 → rc=1（引用被指向）
        kb_miss = make_kb(os.path.join(td, 'kb_miss'), omit='30-曲式.md')
        rc, out = run(kb_miss)
        if rc != 1 or '曲式域' not in out or 'Traceback' in out:
            fails.append(f'域文档缺未 rc=1 点名 rc={rc}: {out[-160:]}')

    if fails:
        print('用例失败：')
        for f in fails:
            print('  -', f)
        return 1
    print('用例通过：rc 0／1／2 口径与 OUT 落盘、逐条点名均正确')
    return 0


if __name__ == '__main__':
    sys.exit(main())
