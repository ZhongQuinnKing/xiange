#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_run — 公开基准样例包跑批（2026-10-13 立，批二 Y1）

逐首过三检器（记谱关／乐理关／谱面体检），出报告卡摘要；
与例子/基准/预期.json 对照（只标记差异，默认不拦——本包验「流程可复现」，
不承诺准确率数字）。--expect-write 用当次结果覆盖预期（定版时跑一次，人工核过）。

用法（在仓根跑）:
    python3 tools/bench_run.py                    # 跑批＋对照
    python3 tools/bench_run.py --expect-write     # 定版：以当次结果写预期
    python3 tools/bench_run.py --dir examples/bench
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_DIR = os.path.join(ROOT, 'examples', 'bench')


def run_tool(script, path, sub=None):
    args = [sys.executable, os.path.join(HERE, script)]
    if sub:
        args.append(sub)
    args.append(path)
    r = subprocess.run(args, capture_output=True, text=True, timeout=180)
    return (r.stdout or '') + (r.stderr or '')


def parse_sev(out):
    m = re.search(r'严重\s*(\d+)\s*处', out)
    return int(m.group(1)) if m else 0


def parse_light(out):
    m = re.search(r'轻\s*(\d+)\s*处', out)
    return int(m.group(1)) if m else 0


def parse_doctor(out):
    """score_doctor 输出：干净句＝0；正常出头但未见干净句＝1（有报）；读不出＝None。"""
    if not out.strip():
        return None
    if '未发现明显异常' in out:
        return 0
    if '文件:' in out:
        return 1
    return None


def check_one(path):
    nc = run_tool('notation_check.py', path)
    tc = run_tool('theory_check.py', path)
    dc = run_tool('score_doctor.py', path, sub='inspect') if os.path.exists(
        os.path.join(HERE, 'score_doctor.py')) else ''
    return {
        'notation_sev': parse_sev(nc),
        'notation_light': parse_light(nc),
        'theory_sev': parse_sev(tc),
        'theory_light': parse_light(tc),
        'doctor_issues': parse_doctor(dc) if dc else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=DEFAULT_DIR)
    ap.add_argument('--expect-write', action='store_true')
    ap.add_argument('--allow-drift', action='store_true',
                    help='工具升级批用：差异只报不拦（默认差异即退出码非零，防退化）')
    ap.add_argument('--json', help='汇总写 JSON（机读）')
    args = ap.parse_args()
    man = json.load(open(os.path.join(args.dir, '清单.json'), encoding='utf-8'))
    results = {}
    diffs = []
    problems = []
    exp_path = os.path.join(args.dir, '预期.json')
    expect = {}
    if os.path.exists(exp_path) and not args.expect_write:
        expect = json.load(open(exp_path, encoding='utf-8')).get('cases', {})
    for item in man['pieces']:
        f = item['file']
        path = os.path.join(args.dir, f)
        res = check_one(path)
        results[f] = res
        kind = item['kind']
        verdict = 'ok'
        if kind == 'clean':
            if res['notation_sev'] != 0 or res['theory_sev'] != 0 or (res['doctor_issues'] or 0) != 0:
                verdict = 'dirty-on-clean'
        else:
            if res['notation_sev'] + res['theory_sev'] == 0:
                verdict = 'clean-on-defect'
        line = (f"{f}: 记谱 严{res['notation_sev']}轻{res['notation_light']}／"
                f"乐理 严{res['theory_sev']}轻{res['theory_light']}／"
                f"体检 {res['doctor_issues']}" if res['doctor_issues'] is not None
                else f"{f}: 记谱 严{res['notation_sev']}轻{res['notation_light']}／"
                     f"乐理 严{res['theory_sev']}轻{res['theory_light']}")
        print(f'{line}  [{kind}]{" << " + verdict if verdict != "ok" else ""}')
        if verdict != 'ok':
            problems.append(f'{f}: {verdict}')
        if expect:
            e = expect.get(f)
            if e and e != res:
                diffs.append(f'{f}: 预期 {e} 实得 {res}')
    if args.expect_write:
        with open(exp_path, 'w', encoding='utf-8') as fh:
            json.dump({'version': 1, 'note': '定版快照（工具升级重跑时差异入版本记录）',
                       'cases': results}, fh, ensure_ascii=False, indent=1)
        print(f'预期已写：{exp_path}')
    if diffs:
        print(f'\n与定版预期有差异 {len(diffs)} 处（工具升级时属正常，记入版本记录）：')
        for d in diffs:
            print(' -', d)
    print(f'\n共 {len(results)} 首跑毕。')
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump({'pieces': results, 'problems': problems, 'diffs': diffs},
                      fh, ensure_ascii=False, indent=1)
        print(f'（JSON 已写 {args.json}）')
    if problems or diffs:
        if args.allow_drift:
            print(f'（--allow-drift：异常 {len(problems)} 项、差异 {len(diffs)} 处，只报不拦）')
            return 0
        print(f'回归不过：异常 {len(problems)} 项、差异 {len(diffs)} 处。'
              f'工具升级批确有预期变化时用 --expect-write 更新快照，或 --allow-drift 只报不拦。')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
