#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine_runner — 引擎抽象层统一入口（2026-10-13 立）

一个入口、一份配置：图入 XML 出，引擎切换只改配置。

    python3 tools/engine_runner.py <输入> --engine <名> --out <目录> [--params k=v ...]

输出：<目录>/<名>.musicxml（统一转换层归一）
      <目录>/<名>.run.json（引擎、版本、参数、耗时、退出态、输入哈希、产物哈希）
退出码：0 成功；2 参数错；3 版本锁不一致；4 引擎运行失败；5 拒收（前置检不过或域外）。

v0 在役：smt（本机仓 + PRAIG 权重）、homr（uvx 隔离缓存）。
备位：oemer／audiveris／tabomr／orpheus 与 smt-next（候批切换，主线位不动）。

环境变量（SMT_ROOT 必填，缺省即报错）：
  SMT_ROOT   SMT 仓根（必填）
  SMT_WEIGHTS  权重目录（默认 <SMT_ROOT>/weights/smt-fp-grandstaff）
  SMT_PY   运行 SMT 的解释器（默认 <SMT_ROOT>/.venv/bin/python，缺则报缺）
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))

EXIT_OK, EXIT_ARGS, EXIT_LOCK, EXIT_RUN, EXIT_REJECT = 0, 2, 3, 4, 5


def sha256_file(path, limit=None):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        while True:
            b = fh.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def find_kern_events(text):
    """bekern 文本是否含音符事件（排除纯表头/控制行）。"""
    for ln in text.split('\n'):
        s = ln.strip()
        if not s or s.startswith('*') or s.startswith('!') or s.startswith('='):
            continue
        for tok in s.split('\t'):
            if re.match(r'^\[?[0-9]+[a-gA-Gr]', tok.strip()):
                return True
    return False


def kern_to_musicxml(kern_text, out_xml):
    """统一转换层（v0）：bekern → 补表头 → music21 → MusicXML。

    复用 bekern_fix.normalize 的 spine 归一口径（分裂/合并感知，2 列式）。
    单列输入先并成双列（music21 对单声部 kern 的解析不稳）。
    """
    sys.path.insert(0, HERE)
    import bekern_fix  # noqa: E402
    import music21  # noqa: E402
    raw = kern_text
    n_spines = 0
    for ln in raw.split('\n'):
        s = ln.strip()
        if s.startswith('**'):
            n_spines = len(s.split('\t'))
            break
    if n_spines <= 1:
        rows = []
        for ln in raw.split('\n'):
            s = ln.strip()
            if not s:
                continue
            if s.startswith('**'):
                continue  # 原单列表头弃用，统一重注双列
            if s.startswith('*-'):
                continue  # 原终止行弃用，统一重注
            if s.startswith('!') or s.startswith('*'):
                rows.append(s + '\t' + s)  # 注释与解释行：双列同写
                continue
            rows.append(ln + '\t' + ln)
        raw = '**kern\t**kern\n' + '\n'.join(rows) + '\n*-\t*-'
    fixed = bekern_fix.normalize(raw)
    tmp = out_xml + '.krn'
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write(fixed)
    try:
        sc = music21.converter.parse(tmp)
    finally:
        os.unlink(tmp)
    if sc is None or len(sc.parts) == 0:
        raise RuntimeError('kern 解析为空（转换层无法出谱）')
    sc.write('musicxml', fp=out_xml)
    return out_xml


# ── 适配器注册表 ────────────────────────────────────────────
# 每栏：check(inp) 前置检；run(inp, outdir, params) → 产物路径或抛异常。

def smt_precheck(inp):
    if os.path.isdir(inp):
        raise Reject('SMT 只收单页单系统图；目录输入请先切行')
    smt_root = os.environ.get('SMT_ROOT')
    if not smt_root:
        raise EnvError('SMT_ROOT 未设置（必填，指向 SMT 仓根）')
    py = os.environ.get('SMT_PY', os.path.join(smt_root, '.venv', 'bin', 'python'))
    if not os.path.exists(py):
        raise EnvError(f'SMT 解释器不存在：{py}（可设 SMT_PY 指定）')
    if not os.path.isdir(smt_root):
        raise EnvError(f'SMT 仓不存在：{smt_root}（检查 SMT_ROOT）')
    return smt_root, py


def smt_prep_image(inp, td):
    """压到高 256 像素（保宽比）——PRAIG 权重位置编码表 h 仅容 62 格（=256/4 减余），
    直喂高分辨图必崩「tensor 98 vs 62」（2026-10-13 实测）。"""
    try:
        import cv2
    except ImportError as e:
        raise EnvError(f'缺 opencv（SMT 压图用）：{e}')
    img = cv2.imread(inp, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RunError(f'读图失败：{inp}')
    h, w = img.shape[:2]
    if h != 256:
        img = cv2.resize(img, (max(1, int(w * 256 / h)), 256))
    out = os.path.join(td, 'smt_in.png')
    cv2.imwrite(out, img)
    return out


def smt_run(inp, outdir, params):
    smt_root, py = smt_precheck(inp)
    weights = os.environ.get(
        'SMT_WEIGHTS', os.path.join(smt_root, 'weights', 'smt-fp-grandstaff'))
    script = os.path.join(smt_root, 'run_smt.py')
    if not os.path.exists(script):
        raise EnvError(f'SMT 入口不存在：{script}')
    krn = os.path.join(outdir, 'smt.krn')
    with tempfile.TemporaryDirectory() as td:
        cwd = os.path.join(td, 'run')
        os.makedirs(cwd, exist_ok=True)
        src = smt_prep_image(inp, td)
        cmd = [py, script, os.path.abspath(src), '-o', krn, '-m', weights]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, cwd=cwd)
    if r.returncode != 0:
        raise RunError(f'SMT 退出码 {r.returncode}：{(r.stderr or r.stdout)[-300:]}')
    if not os.path.exists(krn):
        raise RunError('SMT 未产出 krn')
    with open(krn, encoding='utf-8', errors='replace') as fh:
        text = fh.read()
    if not find_kern_events(text):
        raise RunError('SMT 输出无音符事件（含死行/空转录）')
    out_xml = os.path.join(outdir, 'smt.musicxml')
    kern_to_musicxml(text, out_xml)
    return out_xml


def homr_precheck(inp):
    if os.path.isdir(inp):
        raise Reject('homr 入口收单图；目录输入请先切页')
    exe = shutil.which('uvx') or shutil.which('homr')
    if not exe:
        raise EnvError('homr 入口不存在（需 uvx 或 homr 在 PATH）')
    return exe


def homr_run(inp, outdir, params):
    """homr 产物写在输入文件同目录（输入名.musicxml），非 cwd。

    为复现核输入，先删同路径旧产物（哨兵），跑完确认新生。
    """
    exe = homr_precheck(inp)
    inp_abs = os.path.abspath(inp)
    stem = os.path.splitext(inp_abs)[0]
    nat = stem + '.musicxml'
    if os.path.exists(nat):
        os.unlink(nat)  # 哨兵：确保下面捡到的是本次产物
    cmd = ([exe, 'homr', inp_abs] if os.path.basename(exe) == 'uvx'
           else [exe, inp_abs])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise RunError(f'homr 退出码 {r.returncode}：{(r.stderr or r.stdout)[-300:]}')
    if not os.path.exists(nat):
        raise RunError('homr 未产出 MusicXML（未在输入同路径出现产物）')
    out_xml = os.path.join(outdir, 'homr.musicxml')
    shutil.copyfile(nat, out_xml)
    return out_xml


class Reject(Exception):
    pass


class EnvError(Exception):
    pass


class RunError(Exception):
    pass


REGISTRY = {
    'smt': {'precheck': smt_precheck, 'run': smt_run,
            'version_hint': 'antoniorv6/SMT @ 20d8240（PRAIG 权重）'},
    'homr': {'precheck': homr_precheck, 'run': homr_run,
             'version_hint': 'homr 0.6.2（uvx 隔离缓存）'},
    'oemer': {'precheck': None, 'run': None, 'version_hint': '备位（0.1.5）'},
    'audiveris': {'precheck': None, 'run': None, 'version_hint': '备位（待评）'},
    'tabomr': {'precheck': None, 'run': None, 'version_hint': '备位（专用环境）'},
    'orpheus': {'precheck': None, 'run': None, 'version_hint': '备位（CNN 档）'},
    'smt-next': {'precheck': None, 'run': None, 'version_hint': '候批切换'},
}


def _load_test_stubs():
    """契约测试注入口：ENGINE_RUNNER_STUBS 指向 JSON 时，并入桩引擎。

    JSON 形如 {"名": {"status": "ok|reject|fail", "version_hint": "..."}}。
    只为测试可注入；主线不读此变量（未设即零影响）。
    """
    p = os.environ.get('ENGINE_RUNNER_STUBS')
    if not p or not os.path.exists(p):
        return
    try:
        specs = json.load(open(p, encoding='utf-8'))
    except (ValueError, OSError):
        return
    for name, s in specs.items():
        status = s.get('status', 'ok')

        def _run(inp, outdir, params, _status=status, _name=name):
            if _status == 'reject':
                raise Reject('桩：前置检不过（注入）')
            if _status == 'fail':
                raise RunError('桩：运行失败（注入）')
            out = os.path.join(outdir, _name + '.musicxml')
            with open(out, 'w', encoding='utf-8') as fh:
                fh.write('<?xml version="1.0"?><score-partwise version="3.1">'
                         '<part-list><score-part id="P1"><part-name>stub</part-name>'
                         '</score-part></part-list><part id="P1"><measure number="1"/>'
                         '</part></score-partwise>')
            return out

        REGISTRY[name] = {'precheck': lambda inp: None, 'run': _run,
                          'version_hint': s.get('version_hint', '桩')}


_load_test_stubs()


def main():
    ap = argparse.ArgumentParser(description='引擎抽象层统一入口（图入 XML 出）')
    ap.add_argument('input', help='输入（图／图目录；v0 在役引擎收单图）')
    ap.add_argument('--engine', required=True, choices=sorted(REGISTRY))
    ap.add_argument('--out', required=True, help='输出目录（自动建）')
    ap.add_argument('--params', nargs='*', default=[], help='k=v 附加参数（登记入 run.json）')
    args = ap.parse_args()

    if not os.path.exists(args.input):
        print(f'输入不存在：{args.input}', file=sys.stderr)
        return EXIT_ARGS
    spec = REGISTRY[args.engine]
    if spec['run'] is None:
        print(f'引擎 {args.engine} 为备位（未在役）：{spec["version_hint"]}', file=sys.stderr)
        return EXIT_LOCK

    params = {}
    for kv in args.params:
        if '=' in kv:
            k, v = kv.split('=', 1)
            params[k] = v
    os.makedirs(args.out, exist_ok=True)
    t0 = time.time()
    in_hash = sha256_file(args.input)
    record = {'engine': args.engine, 'version_hint': spec['version_hint'],
              'params': params, 'input': os.path.basename(args.input),
              'input_sha256': in_hash}
    try:
        out_xml = spec['run'](args.input, args.out, params)
        record['status'] = 'ok'
        record['output'] = os.path.basename(out_xml)
        record['output_sha256'] = sha256_file(out_xml)
    except Reject as e:
        record['status'] = 'rejected'
        record['detail'] = str(e)
        _write_record(args, record, t0)
        print(f'拒收：{e}', file=sys.stderr)
        return EXIT_REJECT
    except EnvError as e:
        record['status'] = 'env_missing'
        record['detail'] = str(e)
        _write_record(args, record, t0)
        print(f'环境缺失：{e}', file=sys.stderr)
        return EXIT_RUN
    except RunError as e:
        record['status'] = 'run_failed'
        record['detail'] = str(e)
        _write_record(args, record, t0)
        print(f'引擎运行失败：{e}', file=sys.stderr)
        return EXIT_RUN
    record['elapsed_s'] = round(time.time() - t0, 2)
    _write_record(args, record, t0)
    print(f'{args.engine} 完成：{out_xml}')
    print(f'运行登记：{os.path.join(args.out, args.engine + ".run.json")}')
    return EXIT_OK


def _write_record(args, record, t0):
    record.setdefault('elapsed_s', round(time.time() - t0, 2))
    path = os.path.join(args.out, args.engine + '.run.json')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(record, fh, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    sys.exit(main())
