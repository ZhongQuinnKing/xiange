#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归用例：引擎抽象层壳（engine_runner）契约与失败路径。

判据（设计件第五节）：统一入口的承诺可证——成功路径出 XML 加运行登记
（含输入哈希）；失败路径逐条验（缺输入／备位引擎／拒收／环境缺／运行失败），
各走各的退出码；主线零改动（不 import 具体引擎即可跑）。

跑法：python3 test_engine_runner.py
另：RUN_REAL_ENGINES=1 时附跑本机真引擎冒烟（homr；SMT 视环境），出 XML 即过。
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
RUNNER = os.path.join(TOOLS, 'engine_runner.py')

fails = []


def check(name, cond, detail=''):
    if cond:
        print(f'  ✓ {name}')
    else:
        fails.append(f'{name} {detail}')
        print(f'  ✗ {name} {detail}')


def run(*args, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    r = subprocess.run([sys.executable, RUNNER, *args],
                       capture_output=True, text=True, timeout=300, env=e)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def load_runner():
    spec = importlib.util.spec_from_file_location('engine_runner', RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    er = load_runner()
    td = tempfile.mkdtemp()
    img = os.path.join(td, 'probe.png')
    open(img, 'wb').write(b'\x89PNG\r\n\x1a\n fake')
    stubs = os.path.join(td, 'stubs.json')
    json.dump({'stubok': {'status': 'ok'},
               'stubreject': {'status': 'reject'},
               'stubfail': {'status': 'fail'}},
              open(stubs, 'w', encoding='utf-8'))
    env = {'ENGINE_RUNNER_STUBS': stubs}

    print('① 缺输入：rc=2')
    rc, out = run(os.path.join(td, 'nope.png'), '--engine', 'smt', '--out', td)
    check('rc=2', rc == 2, f'rc={rc}')
    check('报输入不存在', '输入不存在' in out, out[:150])

    print('② 备位引擎：rc=3（版本锁位）')
    rc, out = run(img, '--engine', 'oemer', '--out', td)
    check('rc=3', rc == 3, f'rc={rc}')
    check('报备位', '备位' in out, out[:150])

    print('③ 未知引擎：argparse 拒（rc=2）')
    rc, out = run(img, '--engine', 'nosuch', '--out', td)
    check('rc=2', rc == 2, f'rc={rc}')

    print('④ 拒收路径（注入桩）：rc=5 且登记落盘')
    od = os.path.join(td, 'stub_reject')
    rc, out = run(img, '--engine', 'stubreject', '--out', od, env=env)
    check('rc=5', rc == 5, f'rc={rc}')
    rec_p = os.path.join(od, 'stubreject.run.json')
    ok = os.path.exists(rec_p)
    check('登记落盘', ok, rec_p)
    if ok:
        rec = json.load(open(rec_p, encoding='utf-8'))
        check('status=rejected', rec.get('status') == 'rejected', str(rec)[:200])
        check('输入哈希在场', len(rec.get('input_sha256', '')) == 64, str(rec)[:200])

    print('⑤ 运行失败路径（注入桩）：rc=4')
    od = os.path.join(td, 'stubfail')
    rc, out = run(img, '--engine', 'stubfail', '--out', od, env=env)
    check('rc=4', rc == 4, f'rc={rc}')
    check('报引擎运行失败', '引擎运行失败' in out, out[:200])

    print('⑥ 成功路径（注入桩）：rc=0，XML＋登记齐出')
    od = os.path.join(td, 'stubok')
    rc, out = run(img, '--engine', 'stubok', '--out', od, '--params', 'k=v', env=env)
    check('rc=0', rc == 0, f'rc={rc}')
    rec_p = os.path.join(od, 'stubok.run.json')
    ok = os.path.exists(rec_p) and os.path.exists(os.path.join(od, 'stubok.musicxml'))
    check('XML＋登记齐出', ok, out[:200])
    if ok:
        rec = json.load(open(rec_p, encoding='utf-8'))
        check('params 登记', rec.get('params', {}).get('k') == 'v', str(rec)[:200])
        check('产物哈希在场', len(rec.get('output_sha256', '')) == 64, str(rec)[:200])
        check('耗时登记', 'elapsed_s' in rec, str(rec)[:200])

    print('⑦ 转换层单测：kern 归一 → MusicXML')
    kern = ('**kern\n*M4/4\n=1\n4c\t4e\n4d\t4f\n4e\t4g\n4f\t4a\n==\n*-\n')
    xml = os.path.join(td, 'conv.musicxml')
    try:
        er.kern_to_musicxml(kern, xml)
        ok = os.path.exists(xml) and os.path.getsize(xml) > 500
        check('出 XML', ok, f'size={os.path.getsize(xml) if os.path.exists(xml) else 0}')
        body = open(xml, encoding='utf-8').read()
        check('XML 结构', 'score-partwise' in body and '<note' in body, body[:200])
    except Exception as e:  # noqa: BLE001
        check('出 XML', False, f'异常 {e}')

    if os.environ.get('RUN_REAL_ENGINES') == '1':
        print('⑧ 真引擎冒烟（RUN_REAL_ENGINES=1）：homr 单图')
        real_img = os.environ.get('REAL_IMG')
        if real_img and os.path.exists(real_img):
            od = os.path.join(td, 'real_homr')
            rc, out = run(real_img, '--engine', 'homr', '--out', od)
            check('homr rc=0', rc == 0, out[-300:])
            check('出 XML', os.path.exists(os.path.join(od, 'homr.musicxml')), out[-200:])
        else:
            print('  - 未设 REAL_IMG，跳过')

    if fails:
        print(f'\n失败 {len(fails)} 项：')
        for f in fails:
            print(' -', f)
        return 1
    print('\n全过。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
