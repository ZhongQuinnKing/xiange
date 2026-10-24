# -*- coding: utf-8 -*-
"""Eight tool handlers for the E1 music MCP server (stage 1 + supplement).

Each handler returns exactly the fixed three-piece payload:
    {"result": {...}, "validation": {...}, "confidence": {...}}
The underlying music engines are wrapped, not rewritten.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from common import (
    AUDIVERIS_APP,
    ENGINE_DEPS,
    ENGINE_PATHS,
    LILYPOND,
    MUSIC_PACK,
    ROOT,
    SAMPLES_DIR,
    ToolError,
    check,
    engine_info,
    envelope,
    now_iso,
    read_json,
    require_file,
    resolve_outdir,
    sha256_bytes,
    write_bytes,
    write_json,
)
import wsl_exec

AUDIO_EXT = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aif", ".aiff"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
SCORE_EXT = {".musicxml", ".xml", ".mxl", ".mid", ".midi", ".krn"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"}
MEDIA_EXT = AUDIO_EXT | VIDEO_EXT

TOOL_SPECS = [
    {
        "name": "recognize_score",
        "title": "识谱（谱种识别与路由）",
        "description": "识别谱面图片的谱种（五线谱/六线谱/简谱/方块字谱等）并给出后续引擎路由。本工具不做音符级 OMR，只到谱种识别与路由，不产出 MusicXML。",
        "input": "recognize_score.input.json",
    },
    {
        "name": "omr_score",
        "title": "音符级 OMR（Audiveris）",
        "description": "用 Audiveris 5.11.0 对印刷体五线谱图片/PDF 做音符级识别，产出 MusicXML（.mxl 与解压后的 .musicxml），并用 music21 回读复验音符数。不可识别或非谱面输入会结构化拒绝。",
        "input": "omr_score.input.json",
    },
    {
        "name": "transcribe_audio",
        "title": "音频/视频转谱",
        "description": "音频经 Basic Pitch（ONNX，本地 WSL）转 MIDI，再由 music21 量化生成 MusicXML；同时跑乐理与记谱校验。视频先用 PyAV 提取音轨（16 kHz 单声道 WAV）再走同一链路。",
        "input": "transcribe_audio.input.json",
    },
    {
        "name": "extract_audio",
        "title": "音轨提取（PyAV）",
        "description": "从视频或音频容器中解码音轨，按指定采样率与声道数写出 16-bit PCM WAV；无音轨的视频会以 no_audio_stream 结构化拒绝。",
        "input": "extract_audio.input.json",
    },
    {
        "name": "check_theory",
        "title": "乐理校验",
        "description": "调用 music-pack 的 theory_check：声部交叉、平行五八度、跨度过大、声部密度骤降、小节时值等机械可判项。",
        "input": "check_theory.input.json",
    },
    {
        "name": "check_notation",
        "title": "记谱规范校验",
        "description": "调用 music-pack 的 notation_check：符杠分组、符干方向、休止符布局、谱表分配。只接受未压缩 MusicXML。",
        "input": "check_notation.input.json",
    },
    {
        "name": "convert_transpose",
        "title": "格式互转与移调",
        "description": "用 music21 在 MusicXML / MIDI / MXL 之间互转，并按半音数移调；输出回读复验音符数与移调增量。",
        "input": "convert_transpose.input.json",
    },
    {
        "name": "render_score",
        "title": "渲染出图与 PDF",
        "description": "music21 生成 LilyPond 源，由 LilyPond 2.13.62 输出 PDF 与 PNG。旧版 LilyPond 对中文标题支持有限，会标注。",
        "input": "render_score.input.json",
    },
]


# ---------------------------------------------------------------------------
# WSL engine scripts (self-contained; read control.json from cwd)
# ---------------------------------------------------------------------------

RECOGNIZE_SCRIPT = r"""
import json, subprocess, sys
c = json.load(open('control.json', encoding='utf-8'))
p = subprocess.run([sys.executable, 'engine.py', c['image'], '--json', c['json']],
                   capture_output=True, text=True)
open('engine_stdout.txt', 'w', encoding='utf-8').write(p.stdout)
open('engine_stderr.txt', 'w', encoding='utf-8').write(p.stderr)
open('engine_rc.txt', 'w').write(str(p.returncode))
sys.exit(p.returncode)
"""

TRANSCRIBE_SCRIPT = r"""
import json, subprocess, sys, traceback
c = json.load(open('control.json', encoding='utf-8'))
try:
    from basic_pitch.inference import predict
    model_output, midi_data, note_events = predict(
        c['media'], midi_tempo=float(c.get('tempo', 120.0))
    )
    midi_data.write('out.mid')
    from music21 import converter
    s = converter.parse('out.mid')
    if c.get('quantize', True):
        try:
            s.quantize([4, 8], inPlace=True)
        except Exception:
            pass
    s.write('musicxml', fp='out.musicxml')
    reparsed = converter.parse('out.musicxml')
    try:
        # Long notes are split across bar lines with ties; merge them back so
        # the round-trip count compares note events, not tie segments.
        reparsed.stripTies(inPlace=True)
    except Exception:
        pass
    reparsed_notes = len(reparsed.flatten().notes)
    notes = [
        {"start": float(a), "end": float(b), "midi": int(m), "velocity": float(v)}
        for (a, b, m, v, *_) in note_events
    ]
    try:
        duration = float(midi_data.get_end_time())
    except Exception:
        duration = None
    json.dump({"note_count": len(notes), "reparsed_notes": reparsed_notes,
               "notes": notes, "duration_sec": duration,
               "midi": "out.mid", "musicxml": "out.musicxml"},
              open('result.json', 'w', encoding='utf-8'), ensure_ascii=False)
    p = subprocess.run([sys.executable, 'theory_engine.py', 'out.musicxml',
                        '--json', 'theory.json'], capture_output=True, text=True)
    open('theory_stdout.txt', 'w', encoding='utf-8').write(p.stdout)
    open('theory_stderr.txt', 'w', encoding='utf-8').write(p.stderr)
    open('theory_rc.txt', 'w').write(str(p.returncode))
except Exception as exc:
    traceback.print_exc()
    json.dump({"error": str(exc)}, open('result.json', 'w', encoding='utf-8'), ensure_ascii=False)
    sys.exit(1)
"""

EXTRACT_AUDIO_SCRIPT = r"""
import json, sys, traceback, wave
c = json.load(open('control.json', encoding='utf-8'))
sys.path.insert(0, c['deps'])
try:
    import av
    src = c['media']
    target_rate = int(c.get('sample_rate', 16000))
    want_mono = bool(c.get('mono', True))
    container = av.open(src)
    audio_streams = [s for s in container.streams if s.type == 'audio']
    video_count = sum(1 for s in container.streams if s.type == 'video')
    if not audio_streams:
        streams = [{"type": s.type, "codec": s.codec_context.name} for s in container.streams]
        container.close()
        json.dump({"error": "媒体不含音轨，无法提取音频", "error_code": "no_audio_stream",
                   "streams": streams},
                  open('result.json', 'w', encoding='utf-8'), ensure_ascii=False)
        sys.exit(0)
    st = audio_streams[0]
    src_rate = st.codec_context.sample_rate
    src_ch = st.codec_context.channels
    layout = 'mono' if want_mono else ('stereo' if (src_ch or 1) >= 2 else 'mono')
    resampler = av.AudioResampler(format='s16', layout=layout, rate=target_rate)
    chunks = []
    total = 0
    for frame in container.decode(st):
        for f in resampler.resample(frame):
            chunks.append(f.to_ndarray().tobytes())
            total += f.samples
    for f in resampler.resample(None):
        chunks.append(f.to_ndarray().tobytes())
        total += f.samples
    container_duration = None
    try:
        if container.duration is not None:
            container_duration = round(container.duration / 1000000.0, 3)
    except Exception:
        pass
    container.close()
    channels = 1 if layout == 'mono' else 2
    with wave.open('out.wav', 'wb') as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(target_rate)
        w.writeframes(b''.join(chunks))
    duration = round(total / float(target_rate), 3) if target_rate else None
    json.dump({"ok": True, "wav": "out.wav", "duration_sec": duration,
               "sample_rate": target_rate, "channels": channels, "samples": total,
               "source": {"audio_codec": st.codec_context.name,
                          "source_sample_rate": src_rate,
                          "source_channels": src_ch,
                          "video_streams": video_count,
                          "container_duration_sec": container_duration}},
              open('result.json', 'w', encoding='utf-8'), ensure_ascii=False)
except Exception as exc:
    traceback.print_exc()
    msg = str(exc)
    low = msg.lower()
    if 'no such file' in low or 'not found' in low:
        code = 'input_not_found'
    elif 'invalid data' in low or 'could not open' in low or 'unknown' in low or 'moov' in low:
        code = 'invalid_media'
    else:
        code = 'audio_decode_failed'
    json.dump({"error": msg, "error_code": code},
              open('result.json', 'w', encoding='utf-8'), ensure_ascii=False)
    sys.exit(0)
"""


OMR_SCRIPT = r"""
import json, os, re, subprocess, sys, traceback, zipfile
import xml.etree.ElementTree as ET
c = json.load(open('control.json', encoding='utf-8'))
APP = c['app']
INP = c['input']
OUTDIR = 'omr_out'

def write(obj):
    json.dump(obj, open('result.json', 'w', encoding='utf-8'), ensure_ascii=False)

try:
    os.makedirs(OUTDIR, exist_ok=True)
    cmd = [APP, '-batch', '-export', '-output', OUTDIR, INP]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=int(c.get('timeout', 280)))
    open('omr_stdout.txt', 'w', encoding='utf-8').write(p.stdout or '')
    open('omr_stderr.txt', 'w', encoding='utf-8').write(p.stderr or '')

    log_text = ''
    for name in os.listdir(OUTDIR):
        if name.endswith('.log'):
            log_text += open(os.path.join(OUTDIR, name), encoding='utf-8', errors='replace').read()
    if log_text:
        open('omr.log', 'w', encoding='utf-8').write(log_text)

    mxls = [n for n in os.listdir(OUTDIR) if n.lower().endswith('.mxl')]
    if not mxls:
        blob = (p.stdout or '') + '\n' + (p.stderr or '') + '\n' + log_text
        code = 'omr_failed'
        if 'interline value' in blob or 'too low interline' in blob:
            code = 'image_too_low_res'
        elif 'No image' in blob or 'IIOException' in blob or 'ImageLoading' in blob:
            code = 'invalid_image'
        elif 'No regularly spaced lines found' in blob or 'No staff' in blob:
            code = 'no_staff_detected'
        elif 'FileNotFound' in blob or 'Could not find file' in blob:
            code = 'input_not_found'
        elif 'Error in export' in blob:
            code = 'omr_export_failed'
        write({"error": "Audiveris 未产出 MusicXML", "error_code": code,
               "exit_code": p.returncode,
               "log_tail": (log_text or (p.stdout or ''))[-2500:],
               "stderr_tail": (p.stderr or '')[-1200:]})
        sys.exit(0)

    os.replace(os.path.join(OUTDIR, mxls[0]), 'out.mxl')

    rootfile = None
    with zipfile.ZipFile('out.mxl') as z:
        names = z.namelist()
        if 'META-INF/container.xml' in names:
            try:
                root = ET.fromstring(z.read('META-INF/container.xml'))
                for el in root.iter():
                    if el.tag.split('}')[-1] == 'rootfile':
                        rootfile = el.attrib.get('full-path')
            except Exception:
                rootfile = None
        if not rootfile:
            cands = [n for n in names
                     if n.lower().endswith(('.xml', '.musicxml')) and not n.startswith('META-INF')]
            rootfile = cands[0] if cands else None
        if rootfile:
            open('out.musicxml', 'wb').write(z.read(rootfile))

    from music21 import converter
    s = converter.parse('out.musicxml')
    flat = list(s.flatten().notes)
    note_count = sum(len(n.pitches) for n in flat)
    measures = []
    for part in (s.parts if s.parts else [s]):
        measures.append(len(part.getElementsByClass('Measure')))
    try:
        duration = float(s.duration.quarterLength)
    except Exception:
        duration = None

    head_count = None
    model_measures = None
    omr_path = None
    for name in os.listdir(OUTDIR):
        if name.lower().endswith('.omr'):
            omr_path = os.path.join(OUTDIR, name)
    if omr_path:
        try:
            with zipfile.ZipFile(omr_path) as z:
                sheets = [n for n in z.namelist() if re.search(r'sheet#\d+/sheet#\d+\.xml$', n)]
                heads = 0
                for n in sheets:
                    root = ET.fromstring(z.read(n))
                    heads += sum(1 for el in root.iter() if el.tag == 'head')
                    for el in root.iter():
                        if el.tag == 'page' and el.attrib.get('measure-count'):
                            model_measures = int(el.attrib['measure-count'])
                head_count = heads
        except Exception:
            pass

    page_count = None
    m = re.search(r'(\d+)\s+sheets?\s+in\s+', log_text)
    if m:
        page_count = int(m.group(1))
    raw_measures = None
    m = re.search(r'(\d+)\s+raw measures', log_text)
    if m:
        raw_measures = int(m.group(1))

    warnings = []
    if 'TesseractOCR' in log_text or 'OCR languages' in log_text or 'Missing support for' in log_text:
        warnings.append('Tesseract OCR 语言包为空：文字/歌词识别缺失，音符识别不受影响')
    if 'NOT RELIABLE' in log_text:
        warnings.append('分辨率偏低：Audiveris 标记谱线间距不可靠')

    write({"ok": True, "mxl": "out.mxl", "musicxml": "out.musicxml",
           "note_count": note_count, "measures": measures,
           "parts": len(s.parts) if s.parts else 1,
           "duration_quarter_length": duration,
           "mxl_count": len(mxls),
           "audiveris_model": {"head_count": head_count, "measure_count": model_measures},
           "log": {"page_count": page_count, "raw_measures": raw_measures},
           "warnings": warnings, "exit_code": p.returncode,
           "log_tail": log_text[-1500:]})
except subprocess.TimeoutExpired:
    write({"error": "Audiveris 超时（>280s）", "error_code": "engine_timeout"})
except Exception as exc:
    traceback.print_exc()
    write({"error": str(exc), "error_code": "omr_failed"})
"""


THEORY_SCRIPT = r"""
import json, subprocess, sys
c = json.load(open('control.json', encoding='utf-8'))
args = [sys.executable, 'engine.py', c['score'], '--json', c['json']]
if c.get('span_limit'):
    args += ['--span', str(int(c['span_limit']))]
p = subprocess.run(args, capture_output=True, text=True)
open('engine_stdout.txt', 'w', encoding='utf-8').write(p.stdout)
open('engine_stderr.txt', 'w', encoding='utf-8').write(p.stderr)
open('engine_rc.txt', 'w').write(str(p.returncode))
sys.exit(p.returncode)
"""

CONVERT_SCRIPT = r"""
import json, sys, traceback
from music21 import converter
c = json.load(open('control.json', encoding='utf-8'))
try:
    s = converter.parse(c['score'])
    before = [n.pitch.midi for n in s.flatten().notes if n.isNote]
    try:
        key_before = str(s.analyze('key'))
    except Exception:
        key_before = None
    semitones = int(c.get('semitones', 0))
    t = s.transpose(semitones) if semitones else s
    after = [n.pitch.midi for n in t.flatten().notes if n.isNote]
    t.write(c['format'], fp=c['output'])
    r = converter.parse(c['output'])
    re_notes = [n.pitch.midi for n in r.flatten().notes if n.isNote]
    try:
        key_after = str(r.analyze('key'))
    except Exception:
        key_after = None
    deltas = [b - a for a, b in zip(before, after)]
    json.dump({
        "notes_before": len(before),
        "notes_after": len(after),
        "reparsed_notes": len(re_notes),
        "semitones": semitones,
        "shift_all_equal": bool(deltas) and all(d == semitones for d in deltas),
        "key_before": key_before,
        "key_after": key_after,
        "output": c['output'],
    }, open('result.json', 'w', encoding='utf-8'), ensure_ascii=False)
except Exception as exc:
    traceback.print_exc()
    json.dump({"error": str(exc)}, open('result.json', 'w', encoding='utf-8'), ensure_ascii=False)
    sys.exit(1)
"""

RENDER_SCRIPT = r"""
import json, os, sys, traceback
from music21 import converter
from music21.lily.translate import LilypondConverter
c = json.load(open('control.json', encoding='utf-8'))
try:
    s = converter.parse(c['score'])
    os.makedirs('/tmp/e1bin', exist_ok=True)
    fake = '/tmp/e1bin/lilypond'
    open(fake, 'w').write('#!/bin/sh\necho "GNU LilyPond 2.13.62"\n')
    os.chmod(fake, 0o755)
    os.environ['PATH'] = '/tmp/e1bin:' + os.environ['PATH']
    conv = LilypondConverter()
    conv.loadFromMusic21Object(s)
    conv.writeLyFile(ext='ly', fp='out.ly')
    lines = open('out.ly', encoding='utf-8').read().splitlines()
    out = []
    skip = False
    layout_token = chr(92) + 'layout'
    for ln in lines:
        if 'lilypond-book-preamble.ly' in ln:
            continue
        if ln.strip().startswith('color = #(define-music-function'):
            skip = True
            continue
        if skip:
            if '#})' in ln:
                skip = False
            continue
        if ln.strip().startswith(layout_token):
            break
        out.append(ln)
    out.append(layout_token + ' { }')
    with open('out.clean.ly', 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('\n'.join(out) + '\n')
    json.dump({"ly": "out.clean.ly"}, open('result.json', 'w', encoding='utf-8'))
except Exception as exc:
    traceback.print_exc()
    json.dump({"error": str(exc)}, open('result.json', 'w', encoding='utf-8'), ensure_ascii=False)
    sys.exit(1)
"""


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _score_suffix(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".musicxml", ".xml"):
        return ".musicxml"
    if suffix in (".mid", ".midi"):
        return ".mid"
    if suffix == ".mxl":
        return ".mxl"
    if suffix == ".krn":
        return ".krn"
    return ".musicxml"


def _copy_from_wsl(run_dir: str, name: str, dest: Path) -> Path:
    data = wsl_exec.read_file(run_dir, name)
    return write_bytes(dest, data)


def _engine_meta(name: str, path: Path, rc: int, elapsed: float, wsl: bool) -> dict:
    return {
        "name": name,
        "path": str(path),
        "exists": path.is_file(),
        "exit_code": rc,
        "elapsed_ms": elapsed,
        "runtime": "wsl:" + wsl_exec.WSL_DISTRO if wsl else "windows-python",
    }


def _validations_from_findings(findings: list[dict]) -> tuple[list[dict], int, int]:
    severe = [f for f in findings if f.get("sev") == "严重"]
    soft = [f for f in findings if f.get("sev") == "轻"]
    checks = []
    if severe:
        checks.append(check("severe_findings", "warn", f"发现 {len(severe)} 处严重项", count=len(severe)))
    else:
        checks.append(check("severe_findings", "pass", "无严重项", count=0))
    if soft:
        checks.append(check("soft_findings", "warn", f"发现 {len(soft)} 处待裁项", count=len(soft)))
    else:
        checks.append(check("soft_findings", "pass", "无待裁项", count=0))
    return checks, len(severe), len(soft)


# ---------------------------------------------------------------------------
# 1. recognize_score
# ---------------------------------------------------------------------------

def recognize_score(args: dict) -> dict:
    started = time.time()
    src = require_file(args.get("image_path"), "image_path")
    outdir = resolve_outdir("recognize_score", args.get("output_dir"))
    engine_path = ENGINE_PATHS["router"]
    if not engine_path.is_file():
        raise ToolError(f"谱种路由引擎缺失：{engine_path}", code="engine_missing")

    run_id, run_dir = wsl_exec.new_run()
    suffix = src.suffix.lower() if src.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"} else ".png"
    image_name = "input" + suffix
    wsl_exec.stage_file(run_dir, image_name, src.read_bytes())
    wsl_exec.stage_file(run_dir, "engine.py", engine_path.read_bytes())
    wsl_exec.stage_file(
        run_dir,
        "control.json",
        json.dumps({"image": image_name, "json": "route.json"}, ensure_ascii=False).encode("utf-8"),
    )
    proc = wsl_exec.run_script(run_dir, RECOGNIZE_SCRIPT, timeout=60)

    route: dict | None = None
    route_error = None
    try:
        route = wsl_exec.read_json(run_dir, "route.json")
    except Exception as exc:  # engine failed before writing
        route_error = str(exc)

    engine_stdout = ""
    engine_stderr = ""
    try:
        engine_stdout = wsl_exec.read_text(run_dir, "engine_stdout.txt")
        engine_stderr = wsl_exec.read_text(run_dir, "engine_stderr.txt")
    except Exception:
        pass

    route_dest = outdir / f"{src.stem}_route.json"
    if route is not None:
        write_json(route_dest, route)

    checks = [
        check("input_file", "pass", f"{src.name}，{src.stat().st_size} bytes，sha256={sha256_bytes(src.read_bytes())[:16]}"),
        check(
            "image_decode",
            "pass" if route is not None else "fail",
            "图片已解码并完成谱线检测" if route is not None else f"引擎未产出结果：{route_error or engine_stderr[-400:]}",
        ),
    ]
    spec = (route or {}).get("spec")
    checks.append(
        check(
            "score_type",
            "pass" if spec and spec != "unknown" else "warn",
            f"判定谱种：{spec}" if spec else "未能判定谱种",
        )
    )
    checks.append(
        check(
            "note_level_omr",
            "warn",
            "music-pack 未安装 oemer/SMT 可执行件；本工具只完成谱种识别与路由，不产出 MusicXML 音符",
        )
    )

    result = {
        "tool": "recognize_score",
        "image": str(src),
        "spec": spec,
        "routed_engine": (route or {}).get("engine"),
        "why": (route or {}).get("why"),
        "metrics": {
            "size": (route or {}).get("size"),
            "hlines": (route or {}).get("hlines"),
            "staff5_groups": (route or {}).get("staff5_groups"),
            "staff6_groups": (route or {}).get("staff6_groups"),
            "blocks": (route or {}).get("blocks"),
            "median_block": (route or {}).get("median_block"),
            "ink": (route or {}).get("ink"),
        },
        "artifacts": {"route_report": str(route_dest) if route is not None else None},
        "engine_stdout_tail": engine_stdout[-800:],
        "engine_stderr_tail": engine_stderr[-800:],
    }

    level = "high" if spec in {"五线谱", "六线谱", "简谱"} else "medium"
    basis = [
        "规则启发式：水平谱线形态学检测 + 字符连通域统计，全过程可解释",
        f"检出水平线 {result['metrics']['hlines']} 条，五线组 {result['metrics']['staff5_groups']}，六线组 {result['metrics']['staff6_groups']}",
    ]
    uncertain = [
        "未启用音符级 OMR，未产出 MusicXML；识谱只到谱种与路由层",
        "双谱表页面实测五线组计数会低估（本样例应 2 组、报 1 组），谱种结论仍正确",
    ]
    if spec == "unknown":
        uncertain.append("谱种拒判（unknown），需要更清晰的扫描或人工确认")

    return envelope(
        result,
        checks,
        level,
        basis,
        uncertain,
        _engine_meta("music-pack/工具_谱种路由.py", engine_path, proc["exit_code"], proc["elapsed_ms"], True),
    )


# ---------------------------------------------------------------------------
# 2. omr_score
# ---------------------------------------------------------------------------

OMR_ENGINES = {"audiveris"}


def omr_score(args: dict) -> dict:
    src = require_file(args.get("path"), "path")
    ext = src.suffix.lower()
    if ext not in IMAGE_EXT and ext != ".pdf":
        raise ToolError(
            f"OMR 不接受 {ext or '(无扩展名)'}；支持图片 {sorted(IMAGE_EXT)} 与 .pdf",
            code="unsupported_score_format",
        )
    engine = args.get("engine", "audiveris")
    if engine not in OMR_ENGINES:
        raise ToolError(
            f"不支持的 OMR 引擎：{engine}；当前仅 audiveris（已解包到私有前缀）",
            code="unsupported_engine",
        )
    outdir = resolve_outdir("omr_score", args.get("output_dir"))

    run_id, run_dir = wsl_exec.new_run()
    in_name = "input" + ext
    wsl_exec.stage_file(run_dir, in_name, src.read_bytes())
    wsl_exec.stage_file(
        run_dir,
        "control.json",
        json.dumps({"app": AUDIVERIS_APP, "input": in_name, "timeout": 280}).encode("utf-8"),
    )
    proc = wsl_exec.run_script(run_dir, OMR_SCRIPT, timeout=300)

    data: dict | None = None
    data_error = None
    try:
        data = wsl_exec.read_json(run_dir, "result.json")
    except Exception as exc:
        data_error = str(exc)

    if data is None or not data.get("ok"):
        msg = (data or {}).get("error") or data_error or proc["stderr"][-800:] or "Audiveris 未产出结果"
        code = (data or {}).get("error_code") or "omr_failed"
        try:
            log_text = wsl_exec.read_text(run_dir, "omr.log")
            write_bytes(outdir / f"{src.stem}_omr.log", log_text.encode("utf-8"))
        except Exception:
            pass
        raise ToolError(
            msg,
            code=code,
            detail={
                "exit_code": proc["exit_code"],
                "log_tail": (data or {}).get("log_tail"),
                "stderr_tail": (data or {}).get("stderr_tail"),
            },
        )

    mxl_dest = _copy_from_wsl(run_dir, "out.mxl", outdir / f"{src.stem}.mxl")
    xml_dest = _copy_from_wsl(run_dir, "out.musicxml", outdir / f"{src.stem}.musicxml")
    log_dest: Path | None = None
    try:
        log_dest = _copy_from_wsl(run_dir, "omr.log", outdir / f"{src.stem}_omr.log")
    except Exception:
        log_dest = None

    note_count = int(data.get("note_count") or 0)
    measures = data.get("measures") or []
    # measures are per part; the score's measure count is the per-part count
    measure_total = max(measures) if measures else 0
    model = data.get("audiveris_model") or {}
    head_count = model.get("head_count")
    raw_measures = (data.get("log") or {}).get("raw_measures")
    page_count = (data.get("log") or {}).get("page_count")
    warnings = data.get("warnings") or []

    checks = [
        check(
            "input_file",
            "pass",
            f"{src.name}，{src.stat().st_size} bytes，sha256={sha256_bytes(src.read_bytes())[:16]}",
        ),
        check("engine_exit", "pass" if proc["exit_code"] == 0 else "warn", f"Audiveris 退出码 {proc['exit_code']}"),
        check(
            "musicxml_written",
            "pass" if xml_dest.is_file() and xml_dest.stat().st_size > 0 and mxl_dest.is_file() else "fail",
            f"{mxl_dest.name}（{mxl_dest.stat().st_size} bytes）+ {xml_dest.name}（{xml_dest.stat().st_size} bytes）",
        ),
        check("notes_detected", "pass" if note_count > 0 else "fail", f"music21 回读 {note_count} 个音符"),
        check(
            "omr_model_consistency",
            "pass" if head_count == note_count and note_count > 0 else "warn",
            f"Audiveris 工程件记录 {head_count} 个符头，music21 回读 {note_count} 个音符",
        ),
        check(
            "measure_consistency",
            (
                "pass"
                if page_count == 1 and raw_measures is not None and raw_measures == measure_total
                else "warn"
            ),
            (
                f"单页：Audiveris 日志 {raw_measures} 小节，music21 各声部小节数 {measures}"
                if page_count == 1
                else f"多页或页数未定：日志 raw measures={raw_measures} 不可直接比，music21 各声部小节数 {measures}"
            ),
        ),
        check("page_count", "pass" if page_count and page_count > 0 else "warn", f"页数 {page_count}"),
    ]
    if warnings:
        checks.append(check("engine_warnings", "warn", "；".join(warnings)))

    result = {
        "tool": "omr_score",
        "image": str(src),
        "engine": engine,
        "page_count": page_count,
        "note_count": note_count,
        "measures": measures,
        "measure_count": measure_total,
        "parts": data.get("parts"),
        "duration_quarter_length": data.get("duration_quarter_length"),
        "audiveris_model": model,
        "log": data.get("log"),
        "warnings": warnings,
        "musicxml": str(xml_dest),
        "mxl": str(mxl_dest),
        "artifacts": {
            "musicxml": str(xml_dest),
            "mxl": str(mxl_dest),
            "omr_log": str(log_dest) if log_dest else None,
        },
    }
    level = "medium"
    basis = [
        "Audiveris 5.11.0 以 -batch -export 跑完识别并导出 MusicXML",
        f"music21 回读 {xml_dest.name}：{note_count} 个音符、{measure_total} 小节、{data.get('parts')} 个声部",
        f"Audiveris 工程件记录 {head_count} 个符头，日志记录 {raw_measures} 小节、{page_count} 页",
    ]
    uncertain = [
        "Audiveris 不提供逐音置信度；识别精度受版面、扫描分辨率与字体影响",
        "实测参考：单行合成谱音高 F1 约 0.78，整页约 0.25；本工具不据此外推",
        "只支持印刷体五线谱（Common Western Music Notation），手写谱不支持",
    ]
    if warnings:
        uncertain.extend(warnings)
    return envelope(
        result,
        checks,
        level,
        basis,
        uncertain,
        {
            "name": "Audiveris",
            "version": "5.11.0",
            "path": AUDIVERIS_APP,
            "exists": True,
            "exit_code": proc["exit_code"],
            "elapsed_ms": proc["elapsed_ms"],
            "runtime": "wsl:" + wsl_exec.WSL_DISTRO,
        },
    )


# ---------------------------------------------------------------------------
# 3. transcribe_audio
# ---------------------------------------------------------------------------

def transcribe_audio(args: dict) -> dict:
    src = require_file(args.get("media_path"), "media_path")
    outdir = resolve_outdir("transcribe_audio", args.get("output_dir"))
    ext = src.suffix.lower()
    is_video = ext in VIDEO_EXT
    if not is_video and ext not in AUDIO_EXT:
        raise ToolError(
            f"不支持的音频格式：{ext or '(无扩展名)'}；支持音频 {sorted(AUDIO_EXT)}，"
            f"视频 {sorted(VIDEO_EXT)}（经 PyAV 提取音轨）",
            code="unsupported_media_format",
        )

    quantize = args.get("quantize", True)
    if not isinstance(quantize, bool):
        raise ToolError("quantize 必须是布尔值", code="invalid_argument")
    tempo = float(args.get("tempo", 120.0))
    if not (20 <= tempo <= 400):
        raise ToolError("tempo 必须在 20–400 BPM 之间", code="invalid_argument")

    run_id, run_dir = wsl_exec.new_run()
    media_name = "input" + ext
    wsl_exec.stage_file(run_dir, media_name, src.read_bytes())
    extract_meta: dict | None = None
    if is_video:
        wsl_exec.stage_file(
            run_dir,
            "control.json",
            json.dumps(
                {"deps": ENGINE_DEPS, "media": media_name, "sample_rate": 16000, "mono": True},
                ensure_ascii=False,
            ).encode("utf-8"),
        )
        extract_proc = wsl_exec.run_script(run_dir, EXTRACT_AUDIO_SCRIPT, timeout=180)
        try:
            extract_meta = wsl_exec.read_json(run_dir, "result.json")
        except Exception as exc:
            raise ToolError(
                f"视频音轨提取未产出结果：{exc}",
                code="audio_decode_failed",
                detail={"exit_code": extract_proc["exit_code"], "stderr": extract_proc["stderr"][-800:]},
            ) from exc
        if not extract_meta.get("ok"):
            raise ToolError(
                extract_meta.get("error") or "视频音轨提取失败",
                code=extract_meta.get("error_code") or "audio_decode_failed",
                detail={"streams": extract_meta.get("streams")},
            )
        media_name = "out.wav"
    wsl_exec.stage_file(run_dir, "theory_engine.py", ENGINE_PATHS["theory"].read_bytes())
    wsl_exec.stage_file(
        run_dir,
        "control.json",
        json.dumps(
            {"media": media_name, "quantize": quantize, "tempo": tempo},
            ensure_ascii=False,
        ).encode("utf-8"),
    )
    proc = wsl_exec.run_script(run_dir, TRANSCRIBE_SCRIPT, timeout=240)

    result_data: dict | None = None
    result_error = None
    try:
        result_data = wsl_exec.read_json(run_dir, "result.json")
    except Exception as exc:
        result_error = str(exc)

    if result_data is None or "error" in (result_data or {}):
        msg = (result_data or {}).get("error") or result_error or proc["stderr"][-800:]
        return envelope(
            {"tool": "transcribe_audio", "media": str(src), "error": msg},
            [
                check("input_file", "pass", f"{src.name}，{src.stat().st_size} bytes"),
                check("engine_exit", "fail", f"Basic Pitch 转谱失败：{msg}"),
                check("notes_detected", "fail", "未产出音符"),
            ],
            "low",
            [],
            [msg],
            _engine_meta("basic_pitch + music21", MUSIC_PACK, proc["exit_code"], proc["elapsed_ms"], True),
        )

    midi_dest = _copy_from_wsl(run_dir, "out.mid", outdir / f"{src.stem}.mid")
    xml_dest = _copy_from_wsl(run_dir, "out.musicxml", outdir / f"{src.stem}.musicxml")
    extracted_wav_dest: Path | None = None
    if is_video:
        extracted_wav_dest = _copy_from_wsl(
            run_dir, "out.wav", outdir / f"{src.stem}_extracted.wav"
        )

    # notation_check is zero-dependency and runs on the host
    notation_findings: list[dict] = []
    notation_text = ""
    notation_rc = None
    notation_json = outdir / f"{src.stem}_notation.json"
    try:
        notation_proc = subprocess.run(
            [sys.executable, str(ENGINE_PATHS["notation"]), str(xml_dest), "--json", str(notation_json)],
            capture_output=True,
            timeout=120,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        notation_rc = notation_proc.returncode
        notation_text = notation_proc.stdout.decode("utf-8", "replace")
        if notation_json.is_file():
            notation_findings = read_json(notation_json)
    except Exception as exc:
        notation_text = f"notation_check 运行失败：{exc}"

    theory_findings: list[dict] = []
    theory_text = ""
    theory_rc = None
    theory_json = outdir / f"{src.stem}_theory.json"
    try:
        theory_findings = wsl_exec.read_json(run_dir, "theory.json")
        theory_text = wsl_exec.read_text(run_dir, "theory_stdout.txt")
        theory_rc = int(wsl_exec.read_text(run_dir, "theory_rc.txt").strip() or "-1")
        write_json(theory_json, theory_findings)
    except Exception:
        pass

    note_count = int(result_data.get("note_count") or 0)
    reparsed_count = int(result_data.get("reparsed_notes") or 0)
    theory_checks, theory_severe, theory_soft = _validations_from_findings(theory_findings)
    notation_checks, notation_severe, notation_soft = _validations_from_findings(notation_findings)
    for c in notation_checks:
        c["id"] = "notation_" + c["id"]
    checks = [
        check("input_file", "pass", f"{src.name}，{src.stat().st_size} bytes，sha256={sha256_bytes(src.read_bytes())[:16]}"),
        check("engine_exit", "pass" if proc["exit_code"] == 0 else "warn", f"Basic Pitch/music21 退出码 {proc['exit_code']}"),
        check("notes_detected", "pass" if note_count > 0 else "fail", f"检出 {note_count} 个音符"),
        check("musicxml_written", "pass" if xml_dest.is_file() and xml_dest.stat().st_size > 0 else "fail", f"输出 {xml_dest.name}"),
        check(
            "musicxml_reparse",
            "pass" if reparsed_count == note_count and note_count > 0 else "fail",
            f"music21 回读 {reparsed_count} 个事件（检出 {note_count}）",
        ),
        check(
            "notation_engine_exit",
            "pass" if notation_rc == 0 else "warn",
            f"notation_check 退出码 {notation_rc}",
        ),
        check(
            "theory_engine_exit",
            "pass" if theory_rc == 0 else "warn",
            f"theory_check 退出码 {theory_rc}",
        ),
    ]
    if is_video:
        checks.insert(
            1,
            check(
                "audio_extracted",
                "pass" if extracted_wav_dest and extracted_wav_dest.is_file() else "fail",
                f"PyAV 提取音轨 → {extracted_wav_dest.name if extracted_wav_dest else '未产出'}",
            ),
        )
    checks += theory_checks
    checks += notation_checks

    velocities = [n.get("velocity", 0) for n in result_data.get("notes", [])]
    avg_vel = sum(velocities) / len(velocities) if velocities else 0
    level = "high" if note_count > 0 and proc["exit_code"] == 0 else "medium"
    basis = [
        f"Basic Pitch ONNX 检出 {note_count} 个音符，平均置信 {avg_vel:.3f}",
        "music21 回读 MIDI 并量化到 1/8 后写出 MusicXML，再回读复验",
        f"乐理校验：严重 {theory_severe} 处；记谱校验：严重 {notation_severe} 处",
    ]
    if is_video and extract_meta:
        basis.insert(
            0,
            f"PyAV 解码音轨：{extract_meta.get('duration_sec')}s，"
            f"{extract_meta.get('sample_rate')} Hz，{extract_meta.get('channels')} 声道",
        )
    uncertain = [
        "音频转谱是估计值，未与人工核对；多声部、踏板、连音线不在识别范围",
        "节奏按 1/8 量化，速度按给定 BPM 写入；演奏速度波动会改变时值",
    ]
    if is_video:
        uncertain.append(
            "视频音轨先由 PyAV 解码为 16 kHz 单声道 WAV 再转谱；采样率下降与混单声道会丢失部分泛音/立体声信息"
        )
    result = {
        "tool": "transcribe_audio",
        "media": str(src),
        "source_type": "video" if is_video else "audio",
        "note_count": note_count,
        "notes": result_data.get("notes", [])[:500],
        "notes_truncated": len(result_data.get("notes", [])) > 500,
        "duration_sec": result_data.get("duration_sec"),
        "extracted_audio": (
            {
                "wav": str(extracted_wav_dest),
                "duration_sec": extract_meta.get("duration_sec"),
                "sample_rate": extract_meta.get("sample_rate"),
                "channels": extract_meta.get("channels"),
                "source": extract_meta.get("source"),
            }
            if is_video and extract_meta
            else None
        ),
        "artifacts": {
            "midi": str(midi_dest),
            "musicxml": str(xml_dest),
            "extracted_wav": str(extracted_wav_dest) if extracted_wav_dest else None,
            "theory_json": str(theory_json) if theory_json else None,
            "notation_json": str(notation_json) if notation_json.is_file() else None,
        },
        "theory": {"severe": theory_severe, "soft": theory_soft, "findings": theory_findings},
        "notation": {"severe": notation_severe, "soft": notation_soft, "findings": notation_findings},
        "reports": {"theory": theory_text[-3000:], "notation": notation_text[-3000:]},
    }
    return envelope(
        result,
        checks,
        level,
        basis,
        uncertain,
        {
            "name": "basic_pitch + music21 + theory_check + notation_check",
            "basic_pitch": "ONNX model inside WSL",
            "exit_code": proc["exit_code"],
            "elapsed_ms": proc["elapsed_ms"],
            "runtime": "wsl:" + wsl_exec.WSL_DISTRO,
        },
    )


# ---------------------------------------------------------------------------
# 4. extract_audio
# ---------------------------------------------------------------------------

def extract_audio(args: dict) -> dict:
    src = require_file(args.get("path"), "path")
    ext = src.suffix.lower()
    if ext not in MEDIA_EXT:
        raise ToolError(
            f"音轨提取不接受 {ext or '(无扩展名)'}；支持音频 {sorted(AUDIO_EXT)}，视频 {sorted(VIDEO_EXT)}",
            code="unsupported_media_format",
        )
    sample_rate = args.get("sample_rate", 16000)
    if not isinstance(sample_rate, int) or isinstance(sample_rate, bool) or not (8000 <= sample_rate <= 48000):
        raise ToolError("sample_rate 必须是 8000–48000 的整数", code="invalid_argument")
    mono = args.get("mono", True)
    if not isinstance(mono, bool):
        raise ToolError("mono 必须是布尔值", code="invalid_argument")
    outdir = resolve_outdir("extract_audio", args.get("output_dir"))

    run_id, run_dir = wsl_exec.new_run()
    media_name = "input" + ext
    wsl_exec.stage_file(run_dir, media_name, src.read_bytes())
    wsl_exec.stage_file(
        run_dir,
        "control.json",
        json.dumps(
            {"deps": ENGINE_DEPS, "media": media_name, "sample_rate": sample_rate, "mono": mono},
            ensure_ascii=False,
        ).encode("utf-8"),
    )
    proc = wsl_exec.run_script(run_dir, EXTRACT_AUDIO_SCRIPT, timeout=180)

    data: dict | None = None
    data_error = None
    try:
        data = wsl_exec.read_json(run_dir, "result.json")
    except Exception as exc:
        data_error = str(exc)

    if data is None or not data.get("ok"):
        msg = (data or {}).get("error") or data_error or proc["stderr"][-800:] or "音轨提取失败"
        code = (data or {}).get("error_code") or "audio_decode_failed"
        raise ToolError(
            msg,
            code=code,
            detail={"streams": (data or {}).get("streams"), "exit_code": proc["exit_code"]},
        )

    dest = _copy_from_wsl(run_dir, "out.wav", outdir / f"{src.stem}.wav")
    head = dest.read_bytes()[:12]
    duration = data.get("duration_sec")
    channels = data.get("channels")
    source = data.get("source") or {}
    checks = [
        check(
            "input_file",
            "pass",
            f"{src.name}，{src.stat().st_size} bytes，sha256={sha256_bytes(src.read_bytes())[:16]}",
        ),
        check("engine_exit", "pass" if proc["exit_code"] == 0 else "warn", f"PyAV 解码退出码 {proc['exit_code']}"),
        check(
            "audio_stream",
            "pass",
            f"音轨 {source.get('audio_codec')}，源 {source.get('source_sample_rate')} Hz / {source.get('source_channels')} 声道",
        ),
        check(
            "wav_written",
            "pass" if head[:4] == b"RIFF" and head[8:12] == b"WAVE" else "fail",
            f"{dest.name}（{dest.stat().st_size} bytes，RIFF/WAVE 头）",
        ),
        check("duration", "pass" if duration and duration > 0 else "fail", f"时长 {duration}s"),
        check(
            "sample_rate",
            "pass" if data.get("sample_rate") == sample_rate else "fail",
            f"输出采样率 {data.get('sample_rate')} Hz（请求 {sample_rate}）",
        ),
        check("channels", "pass" if channels in (1, 2) else "fail", f"输出声道数 {channels}"),
    ]
    result = {
        "tool": "extract_audio",
        "media": str(src),
        "wav": str(dest),
        "duration_sec": duration,
        "sample_rate": data.get("sample_rate"),
        "channels": channels,
        "samples": data.get("samples"),
        "source": source,
        "artifacts": {"wav": str(dest)},
    }
    level = "high" if duration and duration > 0 and channels in (1, 2) else "medium"
    basis = [
        "PyAV（依赖目录见 ENGINES.md）解码首个音频流，按请求采样率与声道数重采样",
        f"解出 {data.get('samples')} 帧，{duration}s，{data.get('sample_rate')} Hz，{channels} 声道",
    ]
    uncertain = [
        "重采样与混单声道会改变频谱/声像；不追求听感保真，只为后续转谱",
        "容器声明的时长与实际解码帧数可能略有出入，结果以解码帧数为准",
    ]
    if not mono and (source.get("source_channels") or 1) < 2:
        uncertain.append("源音轨为单声道，请求立体声输出只是复制声道，无信息增益")
    if source.get("source_sample_rate") and sample_rate > source["source_sample_rate"]:
        uncertain.append("目标采样率高于源采样率，上采样不增加信息")
    return envelope(
        result,
        checks,
        level,
        basis,
        uncertain,
        {
            "name": "PyAV",
            "path": ENGINE_DEPS + "/av",
            "exists": True,
            "exit_code": proc["exit_code"],
            "elapsed_ms": proc["elapsed_ms"],
            "runtime": "wsl:" + wsl_exec.WSL_DISTRO,
        },
    )


# ---------------------------------------------------------------------------
# 5. check_theory
# ---------------------------------------------------------------------------

def check_theory(args: dict) -> dict:
    src = require_file(args.get("score_path"), "score_path")
    if src.suffix.lower() not in SCORE_EXT:
        raise ToolError(
            f"乐理校验不接受 {src.suffix}；支持 {sorted(SCORE_EXT)}", code="unsupported_score_format"
        )
    outdir = resolve_outdir("check_theory", args.get("output_dir"))
    engine_path = ENGINE_PATHS["theory"]
    if not engine_path.is_file():
        raise ToolError(f"乐理校验引擎缺失：{engine_path}", code="engine_missing")

    span_limit = args.get("span_limit")
    if span_limit is not None:
        if not isinstance(span_limit, int) or not (1 <= span_limit <= 48):
            raise ToolError("span_limit 必须是 1–48 的整数（半音）", code="invalid_argument")

    run_id, run_dir = wsl_exec.new_run()
    score_name = "score" + _score_suffix(src)
    wsl_exec.stage_file(run_dir, score_name, src.read_bytes())
    wsl_exec.stage_file(run_dir, "engine.py", engine_path.read_bytes())
    wsl_exec.stage_file(
        run_dir,
        "control.json",
        json.dumps(
            {"score": score_name, "json": "findings.json", "span_limit": span_limit},
            ensure_ascii=False,
        ).encode("utf-8"),
    )
    proc = wsl_exec.run_script(run_dir, THEORY_SCRIPT, timeout=120)

    findings: list[dict] | None = None
    findings_error = None
    try:
        findings = wsl_exec.read_json(run_dir, "findings.json")
    except Exception as exc:
        findings_error = str(exc)
    stdout = ""
    stderr = ""
    try:
        stdout = wsl_exec.read_text(run_dir, "engine_stdout.txt")
        stderr = wsl_exec.read_text(run_dir, "engine_stderr.txt")
    except Exception:
        pass

    json_dest = outdir / f"{src.stem}_theory.json"
    text_dest = outdir / f"{src.stem}_theory.txt"
    if findings is not None:
        write_json(json_dest, findings)
    write_bytes(text_dest, stdout.encode("utf-8"))

    if findings is None:
        msg = findings_error or stderr[-800:] or "引擎未产出 JSON"
        return envelope(
            {"tool": "check_theory", "score": str(src), "error": msg},
            [
                check("input_file", "pass", f"{src.name}，{src.stat().st_size} bytes"),
                check("engine_exit", "fail", f"theory_check 退出码 {proc['exit_code']}"),
                check("json_output", "fail", msg),
            ],
            "low",
            [],
            [msg],
            _engine_meta("music-pack/theory_check.py", engine_path, proc["exit_code"], proc["elapsed_ms"], True),
        )

    checks = [
        check("input_file", "pass", f"{src.name}，{src.stat().st_size} bytes，sha256={sha256_bytes(src.read_bytes())[:16]}"),
        check("engine_exit", "pass" if proc["exit_code"] == 0 else "fail", f"theory_check 退出码 {proc['exit_code']}"),
        check("json_output", "pass", f"读到 {len(findings)} 条 findings"),
    ]
    finding_checks, n_severe, n_soft = _validations_from_findings(findings)
    checks += finding_checks

    result = {
        "tool": "check_theory",
        "score": str(src),
        "findings": findings,
        "severe": n_severe,
        "soft": n_soft,
        "artifacts": {"json": str(json_dest), "report": str(text_dest)},
        "report": stdout[-4000:],
        "engine_stderr_tail": stderr[-800:],
    }
    level = "high" if proc["exit_code"] == 0 else "medium"
    basis = [
        "music21 解析后按规则逐小节检查（声部交叉/平行五八度/跨度/密度/时值）",
        f"引擎退出码 {proc['exit_code']}，输出 {len(findings)} 条 findings",
    ]
    uncertain = [
        "E5 声部密度骤降是启发式，合法织体切换也会触发，只作待裁提示",
        "平行五度在流行织体中可能是有意写法，需人裁",
    ]
    return envelope(
        result,
        checks,
        level,
        basis,
        uncertain,
        _engine_meta("music-pack/theory_check.py", engine_path, proc["exit_code"], proc["elapsed_ms"], True),
    )


# ---------------------------------------------------------------------------
# 6. check_notation
# ---------------------------------------------------------------------------

def check_notation(args: dict) -> dict:
    src = require_file(args.get("score_path"), "score_path")
    if src.suffix.lower() not in {".musicxml", ".xml"}:
        raise ToolError(
            "记谱规范校验只接受未压缩 MusicXML（.musicxml/.xml）；.mxl/.mid 请先用 convert_transpose 转成 MusicXML",
            code="unsupported_score_format",
        )
    outdir = resolve_outdir("check_notation", args.get("output_dir"))
    engine_path = ENGINE_PATHS["notation"]
    if not engine_path.is_file():
        raise ToolError(f"记谱规范校验引擎缺失：{engine_path}", code="engine_missing")

    json_dest = outdir / f"{src.stem}_notation.json"
    text_dest = outdir / f"{src.stem}_notation.txt"
    started = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, str(engine_path), str(src), "--json", str(json_dest)],
            capture_output=True,
            timeout=120,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError("notation_check 超时（>120s）", code="engine_timeout") from exc
    elapsed = round((time.time() - started) * 1000, 1)
    stdout = proc.stdout.decode("utf-8", "replace")
    stderr = proc.stderr.decode("utf-8", "replace")
    write_bytes(text_dest, stdout.encode("utf-8"))

    findings: list[dict] | None = None
    if json_dest.is_file():
        try:
            findings = read_json(json_dest)
        except Exception as exc:
            findings = None
            stderr += f"\nJSON 读取失败：{exc}"

    if findings is None:
        msg = stderr[-800:] or "引擎未产出 JSON"
        return envelope(
            {"tool": "check_notation", "score": str(src), "error": msg},
            [
                check("input_file", "pass", f"{src.name}，{src.stat().st_size} bytes"),
                check("engine_exit", "fail", f"notation_check 退出码 {proc.returncode}"),
                check("json_output", "fail", msg),
            ],
            "low",
            [],
            [msg],
            _engine_meta("music-pack/notation_check.py", engine_path, proc.returncode, elapsed, False),
        )

    checks = [
        check("input_file", "pass", f"{src.name}，{src.stat().st_size} bytes，sha256={sha256_bytes(src.read_bytes())[:16]}"),
        check("engine_exit", "pass" if proc.returncode == 0 else "fail", f"notation_check 退出码 {proc.returncode}"),
        check("json_output", "pass", f"读到 {len(findings)} 条 findings"),
    ]
    finding_checks, n_severe, n_soft = _validations_from_findings(findings)
    checks += finding_checks

    meter = _meter_of(src)
    checks.append(
        check(
            "meter_coverage",
            "pass" if meter in {"4/4", "6/4"} else "warn",
            f"拍号 {meter}；引擎实测覆盖 4/4（6/4 部分规则），其余拍号标 [?]",
        )
    )

    n_severe = sum(1 for f in findings if f.get("sev") == "严重")
    n_soft = sum(1 for f in findings if f.get("sev") == "轻")
    result = {
        "tool": "check_notation",
        "score": str(src),
        "meter": meter,
        "findings": findings,
        "severe": n_severe,
        "soft": n_soft,
        "artifacts": {"json": str(json_dest), "report": str(text_dest)},
        "report": stdout[-4000:],
        "engine_stderr_tail": stderr[-800:],
    }
    level = "high" if proc.returncode == 0 and meter in {"4/4", "6/4"} else "medium"
    basis = [
        "零依赖 ElementTree 解析，按符杠/符干/休止符/谱表规则逐项检查",
        f"引擎退出码 {proc.returncode}，输出 {len(findings)} 条 findings",
    ]
    uncertain = [
        "复拍子按附点单位分组；本器实测覆盖 4/4，其余拍号与十六分次级符杠规则标 [?]",
        "N1a 面向器乐谱；声乐谱（含歌词者）按字分杠合法，已跳过",
        "N2b 只对钢琴双谱表与 RH/LH 命名谱生效",
    ]
    return envelope(
        result,
        checks,
        level,
        basis,
        uncertain,
        _engine_meta("music-pack/notation_check.py", engine_path, proc.returncode, elapsed, False),
    )


def _meter_of(path: Path) -> str:
    try:
        import xml.etree.ElementTree as ET

        root = ET.parse(path).getroot()
        for el in root.iter():
            tag = el.tag.split("}")[-1] if isinstance(el.tag, str) else ""
            if tag == "time":
                beats = beat_type = None
                for child in el:
                    ctag = child.tag.split("}")[-1]
                    if ctag == "beats":
                        beats = (child.text or "").strip()
                    elif ctag == "beat-type":
                        beat_type = (child.text or "").strip()
                if beats and beat_type:
                    return f"{beats}/{beat_type}"
    except Exception:
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# 7. convert_transpose
# ---------------------------------------------------------------------------

FORMAT_EXT = {"musicxml": ".musicxml", "midi": ".mid", "mxl": ".mxl"}


def convert_transpose(args: dict) -> dict:
    src = require_file(args.get("score_path"), "score_path")
    if src.suffix.lower() not in SCORE_EXT:
        raise ToolError(
            f"格式互转不接受 {src.suffix}；支持 {sorted(SCORE_EXT)}", code="unsupported_score_format"
        )
    fmt = args.get("output_format", "musicxml")
    if fmt not in FORMAT_EXT:
        raise ToolError("output_format 必须是 musicxml / midi / mxl", code="invalid_argument")
    semitones = args.get("semitones", 0)
    if not isinstance(semitones, int) or not (-24 <= semitones <= 24):
        raise ToolError("semitones 必须是 -24–24 的整数", code="invalid_argument")
    outdir = resolve_outdir("convert_transpose", args.get("output_dir"))

    run_id, run_dir = wsl_exec.new_run()
    score_name = "score" + _score_suffix(src)
    out_name = "out" + FORMAT_EXT[fmt]
    wsl_exec.stage_file(run_dir, score_name, src.read_bytes())
    wsl_exec.stage_file(
        run_dir,
        "control.json",
        json.dumps(
            {"score": score_name, "format": fmt, "semitones": semitones, "output": out_name},
            ensure_ascii=False,
        ).encode("utf-8"),
    )
    proc = wsl_exec.run_script(run_dir, CONVERT_SCRIPT, timeout=120)

    data: dict | None = None
    data_error = None
    try:
        data = wsl_exec.read_json(run_dir, "result.json")
    except Exception as exc:
        data_error = str(exc)

    if data is None or "error" in (data or {}):
        msg = (data or {}).get("error") or data_error or proc["stderr"][-800:]
        return envelope(
            {"tool": "convert_transpose", "score": str(src), "error": msg},
            [
                check("input_file", "pass", f"{src.name}，{src.stat().st_size} bytes"),
                check("engine_exit", "fail", f"music21 转换失败：{msg}"),
                check("output_written", "fail", "未产出目标文件"),
            ],
            "low",
            [],
            [msg],
            _engine_meta("music21", MUSIC_PACK, proc["exit_code"], proc["elapsed_ms"], True),
        )

    dest = _copy_from_wsl(run_dir, out_name, outdir / f"{src.stem}_transposed{FORMAT_EXT[fmt]}")
    checks = [
        check("input_file", "pass", f"{src.name}，{src.stat().st_size} bytes，sha256={sha256_bytes(src.read_bytes())[:16]}"),
        check("engine_exit", "pass" if proc["exit_code"] == 0 else "fail", f"music21 退出码 {proc['exit_code']}"),
        check("output_written", "pass" if dest.is_file() and dest.stat().st_size > 0 else "fail", f"输出 {dest.name}（{dest.stat().st_size if dest.is_file() else 0} bytes）"),
        check(
            "note_count_preserved",
            "pass" if data.get("notes_before") == data.get("notes_after") else "fail",
            f"{data.get('notes_before')} → {data.get('notes_after')} 音符",
        ),
        check(
            "reparse",
            "pass" if data.get("reparsed_notes") == data.get("notes_after") else "fail",
            f"回读 {data.get('reparsed_notes')} 音符",
        ),
        check(
            "transpose_applied",
            "pass" if (semitones == 0 or data.get("shift_all_equal")) else "fail",
            f"每个音符增量均为 {semitones} 半音" if semitones else "未移调",
        ),
    ]
    level = "high" if all(c["status"] == "pass" for c in checks) else "medium"
    result = {
        "tool": "convert_transpose",
        "score": str(src),
        "output_format": fmt,
        "semitones": semitones,
        "notes_before": data.get("notes_before"),
        "notes_after": data.get("notes_after"),
        "reparsed_notes": data.get("reparsed_notes"),
        "key_before": data.get("key_before"),
        "key_after": data.get("key_after"),
        "artifacts": {"output": str(dest)},
    }
    basis = [
        "music21 解析原谱、移调并写出目标格式，再回读目标文件复验",
        f"音符数 {data.get('notes_before')} → {data.get('notes_after')}，回读 {data.get('reparsed_notes')}",
    ]
    uncertain = [
        "MIDI 目标格式不携带排版/符号层信息（连音线、力度、踏板等会丢失）",
        "调性分析是 music21 的估计值，异名同音可能有不同写法",
    ]
    return envelope(
        result,
        checks,
        level,
        basis,
        uncertain,
        _engine_meta("music21", MUSIC_PACK, proc["exit_code"], proc["elapsed_ms"], True),
    )


# ---------------------------------------------------------------------------
# 8. render_score
# ---------------------------------------------------------------------------

def render_score(args: dict) -> dict:
    src = require_file(args.get("score_path"), "score_path")
    if src.suffix.lower() not in SCORE_EXT:
        raise ToolError(
            f"渲染不接受 {src.suffix}；支持 {sorted(SCORE_EXT)}", code="unsupported_score_format"
        )
    formats = args.get("formats", ["pdf", "png"])
    if not isinstance(formats, list) or not formats:
        raise ToolError("formats 必须是非空数组", code="invalid_argument")
    formats = [str(f).lower() for f in formats]
    if any(f not in {"pdf", "png"} for f in formats):
        raise ToolError("formats 只支持 pdf / png", code="invalid_argument")
    if not LILYPOND.is_file():
        raise ToolError(f"LilyPond 不可用：{LILYPOND}", code="engine_missing")
    outdir = resolve_outdir("render_score", args.get("output_dir"))

    run_id, run_dir = wsl_exec.new_run()
    score_name = "score" + _score_suffix(src)
    wsl_exec.stage_file(run_dir, score_name, src.read_bytes())
    wsl_exec.stage_file(
        run_dir,
        "control.json",
        json.dumps({"score": score_name}, ensure_ascii=False).encode("utf-8"),
    )
    proc = wsl_exec.run_script(run_dir, RENDER_SCRIPT, timeout=120)

    data: dict | None = None
    data_error = None
    try:
        data = wsl_exec.read_json(run_dir, "result.json")
    except Exception as exc:
        data_error = str(exc)
    if data is None or "error" in (data or {}):
        msg = (data or {}).get("error") or data_error or proc["stderr"][-800:]
        return envelope(
            {"tool": "render_score", "score": str(src), "error": msg},
            [
                check("input_file", "pass", f"{src.name}，{src.stat().st_size} bytes"),
                check("lilypond_source", "fail", f"music21 生成 LilyPond 失败：{msg}"),
            ],
            "low",
            [],
            [msg],
            _engine_meta("music21/LilypondConverter", MUSIC_PACK, proc["exit_code"], proc["elapsed_ms"], True),
        )

    ly_bytes = wsl_exec.read_file(run_dir, "out.clean.ly")
    title = args.get("title")
    if title is not None:
        if not isinstance(title, str) or not title.strip():
            raise ToolError("title 必须是非空字符串", code="invalid_argument")
        ly_text = ly_bytes.decode("utf-8", "replace")
        # Keep the title as text, not LilyPond code: drop quote/backslash/braces/
        # comment characters before it is inserted into the .ly header.
        safe_title = re.sub(r'[\\"{}%#]', " ", title).strip()
        ly_text, n = re.subn(r'(title\s*=\s*")[^"]*(")', lambda m: m.group(1) + safe_title + m.group(2), ly_text, count=1)
        if n == 0:
            ly_text = ly_text.replace("\\header {", '\\header {\n title = "' + safe_title + '"', 1)
        ly_bytes = ly_text.encode("utf-8")
    ly_dest = write_bytes(outdir / f"{src.stem}.ly", ly_bytes)

    lily_args = [str(LILYPOND)]
    if "pdf" in formats:
        lily_args.append("--pdf")
    if "png" in formats:
        lily_args.append("--png")
    lily_args += ["-o", src.stem, ly_dest.name]
    started = time.time()
    try:
        lily = subprocess.run(
            lily_args,
            cwd=str(outdir),
            capture_output=True,
            timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError("LilyPond 渲染超时（>180s）", code="engine_timeout") from exc
    elapsed = round((time.time() - started) * 1000, 1)
    stdout = lily.stdout.decode("utf-8", "replace")
    stderr = lily.stderr.decode("utf-8", "replace")
    write_bytes(outdir / f"{src.stem}_lilypond.log", (stdout + "\n" + stderr).encode("utf-8"))

    pdfs = sorted(outdir.glob(src.stem + "*.pdf"))
    pngs = sorted(outdir.glob(src.stem + "*.png"))
    pdf_bytes = pdfs[0].read_bytes() if pdfs else b""
    png_bytes = pngs[0].read_bytes() if pngs else b""

    checks = [
        check("input_file", "pass", f"{src.name}，{src.stat().st_size} bytes，sha256={sha256_bytes(src.read_bytes())[:16]}"),
        check("lilypond_source", "pass" if ly_dest.stat().st_size > 0 else "fail", f"{ly_dest.name}（{ly_dest.stat().st_size} bytes）"),
        check(
            "lilypond_exit",
            "pass" if lily.returncode == 0 else ("warn" if (pdfs or pngs) else "fail"),
            f"LilyPond 退出码 {lily.returncode}",
        ),
    ]
    if "pdf" in formats:
        checks.append(
            check(
                "pdf_output",
                "pass" if pdf_bytes.startswith(b"%PDF") else "fail",
                f"{pdfs[0].name}（{len(pdf_bytes)} bytes，%PDF 头）" if pdfs else "未产出 PDF",
            )
        )
    if "png" in formats:
        checks.append(
            check(
                "png_output",
                "pass" if png_bytes.startswith(b"\x89PNG\r\n\x1a\n") else "fail",
                f"{pngs[0].name}（{len(png_bytes)} bytes，PNG 头）" if pngs else "未产出 PNG",
            )
        )
    if title and any(ord(ch) > 127 for ch in title):
        checks.append(
            check("cjk_title", "warn", "标题含非 ASCII 字符；LilyPond 2.13.62 的中文字形支持未保证")
        )

    level = "high" if lily.returncode == 0 and (pdfs or pngs) else ("medium" if (pdfs or pngs) else "low")
    result = {
        "tool": "render_score",
        "score": str(src),
        "title": title or _ly_title(ly_dest),
        "formats": formats,
        "page_count_png": len(pngs),
        "artifacts": {
            "ly": str(ly_dest),
            "pdf": [str(p) for p in pdfs],
            "png": [str(p) for p in pngs],
            "lilypond_log": str(outdir / f"{src.stem}_lilypond.log"),
        },
        "lilypond": {"version": "2.13.62", "path": str(LILYPOND), "exit_code": lily.returncode},
        "stdout_tail": stdout[-1200:],
        "stderr_tail": stderr[-1200:],
    }
    basis = [
        "music21 的 LilypondConverter 生成 .ly，适配旧版语法后交给 LilyPond 2.13.62",
        f"LilyPond 退出码 {lily.returncode}；产出 {len(pdfs)} 个 PDF、{len(pngs)} 个 PNG",
    ]
    uncertain = [
        "LilyPond 2.13.62（2011 年）较旧，复杂现代记谱语法可能不支持",
        "中文标题/歌词的字形支持未保证；当前样例使用 ASCII 标题",
        "分页与版式由旧版 LilyPond 决定，未做 A4 精细排版",
    ]
    return envelope(
        result,
        checks,
        level,
        basis,
        uncertain,
        _engine_meta("music21 + LilyPond", LILYPOND, lily.returncode, elapsed, False),
    )


def _ly_title(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'title\s*=\s*"([^"]*)"', text)
        return m.group(1) if m else None
    except Exception:
        return None


TOOL_HANDLERS = {
    "recognize_score": recognize_score,
    "omr_score": omr_score,
    "transcribe_audio": transcribe_audio,
    "extract_audio": extract_audio,
    "check_theory": check_theory,
    "check_notation": check_notation,
    "convert_transpose": convert_transpose,
    "render_score": render_score,
}
