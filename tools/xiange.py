#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""xiange — 统一 CLI 壳（route／check／fix／export／doctor／selfcheck）

一个入口转发到既有工具；doctor 做环境自检（缺项直接给修复命令）；
selfcheck 跑判据级自测全列并出摘要。

用法:
  python3 tools/xiange.py route  谱图.png
  python3 tools/xiange.py check  谱.musicxml
  python3 tools/xiange.py fix    谱.musicxml [--dry-run]
  python3 tools/xiange.py export 谱.musicxml --out 目录 --title 曲名
  python3 tools/xiange.py doctor [--json]
  python3 tools/xiange.py selfcheck [--json]

退出码（统一约定）：0 成功｜2 参数或输入错误｜3 环境缺失｜4 运行失败｜5 拒收
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

EXIT_OK, EXIT_ARGS, EXIT_ENV, EXIT_RUN, EXIT_REJECT = 0, 2, 3, 4, 5

DISPATCH = {
    'route': '工具_谱种路由.py',
    'check': 'notation_check.py',
    'fix': 'notation_fix.py',
    'export': 'export_pack.py',
}


def run_tool(script, argv):
    cmd = [sys.executable, os.path.join(HERE, script)] + argv
    r = subprocess.run(cmd)
    return r.returncode


def _mod_ok(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def doctor(json_out=False):
    checks = []  # (档, 名, 状态 ok/warn/miss, 提示或修复命令)

    py = sys.version_info
    checks.append(('核心', f'Python {py.major}.{py.minor}.{py.micro}',
                   'ok' if py >= (3, 10) else 'miss', '需 Python 3.10 及以上'))
    for m in ('music21', 'numpy'):
        checks.append(('核心', f'依赖 {m}', 'ok' if _mod_ok(m) else 'miss',
                       'bash install.sh core'))
    for m, tier in (('verovio', '渲染'), ('cairosvg', '渲染'), ('PIL', '渲染')):
        checks.append((tier, f'依赖 {m}', 'ok' if _mod_ok(m) else 'warn',
                       'bash install.sh render'))
    checks.append(('浏览器', '依赖 playwright', 'ok' if _mod_ok('playwright') else 'warn',
                   'bash install.sh browser'))
    checks.append(('输入路由', '依赖 cv2', 'ok' if _mod_ok('cv2') else 'warn',
                   'bash install.sh vision'))

    smt = os.environ.get('SMT_ROOT', '')
    if smt and os.path.isdir(smt):
        checks.append(('外部引擎', 'SMT（SMT_ROOT）', 'ok', ''))
    else:
        checks.append(('外部引擎', 'SMT（SMT_ROOT）', 'warn',
                       'export SMT_ROOT=<SMT 仓目录>（外部引擎非 pip 依赖，接入见 docs/03）'))
    hv = subprocess.run(['uvx', '--version'], capture_output=True, text=True)
    checks.append(('外部引擎', 'homr（uvx）', 'ok' if hv.returncode == 0 else 'warn',
                   '装 uv 后 `uvx homr --help` 自证；见 docs/引擎版本表'))
    checks.append(('外部引擎', 'oemer', 'info' if not os.environ.get('OEMER_ROOT') else 'ok',
                   '独立 venv 安装，路径经 OEMER_ROOT 指定（见 docs/03）'))

    fonts = os.path.join(ROOT, 'assets', 'fonts')
    has_font = os.path.isdir(fonts) and any(f.endswith(('.otf', '.ttf'))
                                            for f in os.listdir(fonts))
    checks.append(('字体', 'assets/fonts', 'ok' if has_font else 'warn',
                   '随包本应自带；缺则重新 git clone 完整仓'))

    core_miss = [c for c in checks if c[0] == '核心' and c[2] == 'miss']
    if json_out:
        print(json.dumps({'checks': [{'tier': t, 'name': n, 'status': s, 'hint': h}
                                     for t, n, s, h in checks],
                          'core_ok': not core_miss}, ensure_ascii=False, indent=1))
    else:
        mark = {'ok': '[OK]  ', 'warn': '[注意]', 'miss': '[缺]  ', 'info': '[说明]'}
        cur = ''
        for t, n, s, h in checks:
            if t != cur:
                print(f'== {t} ==')
                cur = t
            line = f'  {mark.get(s, s)} {n}'
            if h and s != 'ok':
                line += f'  → {h}'
            print(line)
        print('\ndoctor 结论：' + ('核心档就绪' if not core_miss else '核心档缺件，见上'))
    return EXIT_ENV if core_miss else EXIT_OK


def selfcheck(json_out=False, list_only=False):
    tdir = os.path.join(HERE, 'tests')
    suites = sorted(f for f in os.listdir(tdir)
                    if f.startswith('test_') and f.endswith('.py'))
    if list_only:
        print('\n'.join(suites))
        return EXIT_OK
    rows = []
    for s in suites:
        r = subprocess.run([sys.executable, os.path.join(tdir, s)],
                           capture_output=True, text=True)
        tail = (r.stdout or '').strip().splitlines()
        rows.append({'suite': s, 'rc': r.returncode,
                     'tail': tail[-1][:72] if tail else ''})
        print(f"{'✓' if r.returncode == 0 else '✗'} {s}  {rows[-1]['tail']}")
    ok = sum(1 for r in rows if r['rc'] == 0)
    if json_out:
        print(json.dumps({'total': len(rows), 'passed': ok, 'rows': rows},
                         ensure_ascii=False, indent=1))
    else:
        print(f'\nselfcheck：{ok}/{len(rows)} 套通过')
    return EXIT_OK if ok == len(rows) else EXIT_RUN


def main():
    ap = argparse.ArgumentParser(prog='xiange', description='弦歌统一入口（壳）')
    ap.add_argument('command', choices=['route', 'check', 'fix', 'export',
                                        'doctor', 'selfcheck'])
    ap.add_argument('args', nargs=argparse.REMAINDER, help='透传给对应工具的原始参数')
    ns = ap.parse_args()
    if ns.command == 'doctor':
        return doctor(json_out='--json' in ns.args)
    if ns.command == 'selfcheck':
        return selfcheck(json_out='--json' in ns.args, list_only='--list' in ns.args)
    script = DISPATCH[ns.command]
    if not os.path.exists(os.path.join(HERE, script)):
        sys.stderr.write(f'缺件：tools/{script}（请用完整仓）\n')
        return EXIT_ENV
    return run_tool(script, ns.args)


if __name__ == '__main__':
    sys.exit(main())
