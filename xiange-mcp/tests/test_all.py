# -*- coding: utf-8 -*-
"""One-command internal test for the E1 music MCP server.

Run from the install directory:
    python tests/test_all.py

It starts server.py as a child process, performs the MCP handshake, calls all
eight tools on the bundled samples, runs eight negative controls, and writes
every response envelope plus a summary under logs/ and samples/.
Exit code 0 means every asserted expectation held.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "server" / "server.py"
LOGS = ROOT / "logs"
SAMPLES = ROOT / "samples"
SHARED = SAMPLES / "shared"

EXPECTED_TOOLS = [
    "recognize_score",
    "omr_score",
    "transcribe_audio",
    "extract_audio",
    "check_theory",
    "check_notation",
    "convert_transpose",
    "render_score",
]

TOOL_CASES = [
    {
        "id": 101,
        "tool": "recognize_score",
        "args": {"image_path": str(SHARED / "ode_page.png")},
        "expect": {"is_error": False, "status_in": ["pass", "warn", "partial"]},
    },
    {
        "id": 102,
        "tool": "transcribe_audio",
        "args": {"media_path": str(SHARED / "ode_sine.wav"), "tempo": 120, "quantize": True},
        "expect": {"is_error": False, "status_in": ["pass", "warn"]},
    },
    {
        "id": 103,
        "tool": "check_theory",
        "args": {"score_path": str(SHARED / "ode_excerpt.musicxml")},
        "expect": {"is_error": False, "status_in": ["pass", "warn"]},
    },
    {
        "id": 104,
        "tool": "check_notation",
        "args": {"score_path": str(SHARED / "ode_excerpt.musicxml")},
        "expect": {"is_error": False, "status_in": ["pass", "warn"]},
    },
    {
        "id": 105,
        "tool": "convert_transpose",
        "args": {
            "score_path": str(SHARED / "ode_excerpt.musicxml"),
            "output_format": "musicxml",
            "semitones": 2,
        },
        "expect": {"is_error": False, "status_in": ["pass", "warn"]},
    },
    {
        "id": 106,
        "tool": "render_score",
        "args": {
            "score_path": str(SHARED / "ode_excerpt.musicxml"),
            "formats": ["pdf", "png"],
        },
        "expect": {"is_error": False, "status_in": ["pass", "warn"]},
    },
    {
        "id": 107,
        "tool": "omr_score",
        "args": {"path": str(SHARED / "omr_page_300dpi.png")},
        "expect": {
            "is_error": False,
            "status_in": ["pass", "warn"],
            "note_count_equals": 38,
            "head_count_equals": 38,
            "min_measures": 8,
        },
    },
    {
        "id": 108,
        "tool": "extract_audio",
        "args": {"path": str(SHARED / "sample_av_10s.mp4")},
        "expect": {
            "is_error": False,
            "status_in": ["pass", "warn"],
            "channels_equals": 1,
            "sample_rate_equals": 16000,
            "min_duration": 9.5,
        },
    },
    {
        "id": 109,
        "tool": "transcribe_audio",
        "args": {"media_path": str(SHARED / "sample_av_10s.mp4"), "tempo": 120, "quantize": True},
        "expect": {
            "is_error": False,
            "status_in": ["pass", "warn"],
            "min_note_count": 1,
            "source_type": "video",
        },
    },
]

NEGATIVE_CASES = [
    {
        "id": 201,
        "tool": "check_theory",
        "args": {"score_path": str(SHARED / "faulty_theory.musicxml")},
        "expect": {"is_error": False, "status_in": ["warn"], "min_severe": 1},
    },
    {
        "id": 202,
        "tool": "check_notation",
        "args": {"score_path": str(SHARED / "faulty_notation.musicxml")},
        "expect": {"is_error": False, "status_in": ["warn"], "min_severe": 1},
    },
    {
        "id": 203,
        "tool": "transcribe_audio",
        "args": {"media_path": str(SHARED / "sample_video_only_10s.mp4")},
        "expect": {"is_error": True, "error_code": "no_audio_stream"},
    },
    {
        "id": 204,
        "tool": "omr_score",
        "args": {"path": str(SHARED / "corrupt.png")},
        "expect": {"is_error": True, "error_code": "invalid_image"},
    },
    {
        "id": 205,
        "tool": "omr_score",
        "args": {"path": str(SHARED / "no_such_score.png")},
        "expect": {"is_error": True, "error_code": "input_not_found"},
    },
    {
        "id": 206,
        "tool": "extract_audio",
        "args": {"path": str(SHARED / "no_such_media.mp4")},
        "expect": {"is_error": True, "error_code": "input_not_found"},
    },
    {
        "id": 207,
        "tool": "omr_score",
        "args": {"path": str(SHARED / "not_a_score.png")},
        "expect": {"is_error": True, "error_code": "no_staff_detected"},
    },
    {
        "id": 208,
        "tool": "omr_score",
        "args": {"path": str(SHARED / "ode_page.png")},
        "expect": {"is_error": True, "error_code": "image_too_low_res"},
    },
]


class Server:
    def __init__(self) -> None:
        LOGS.mkdir(parents=True, exist_ok=True)
        self.stderr_path = LOGS / "test_server_stderr.txt"
        self.stderr_file = open(self.stderr_path, "w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, str(SERVER)],
            cwd=str(ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._stderr_thread = threading.Thread(target=self._pump_stderr, daemon=True)
        self._stderr_thread.start()
        self._timer = threading.Timer(420, self._kill)
        self._timer.daemon = True
        self._timer.start()

    def _pump_stderr(self) -> None:
        for line in self.proc.stderr:  # type: ignore[union-attr]
            self.stderr_file.write(line.decode("utf-8", "replace"))
            self.stderr_file.flush()

    def _kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()

    def send(self, obj: dict) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n"
        assert self.proc.stdin is not None
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def recv(self) -> dict:
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("server closed stdout")
        return json.loads(line.decode("utf-8"))

    def close(self) -> int:
        try:
            self.send({"jsonrpc": "2.0", "method": "exit"})
            assert self.proc.stdin is not None
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self._timer.cancel()
        self._stderr_thread.join(timeout=2)
        self.stderr_file.close()
        return self.proc.returncode


def envelope_errors(payload: dict) -> list[str]:
    errs = []
    if set(payload) != {"result", "validation", "confidence"}:
        errs.append(f"top-level keys are {sorted(payload)}")
        return errs
    v = payload["validation"]
    if not isinstance(v, dict):
        return ["validation is not an object"]
    for key in ("status", "checks", "engine"):
        if key not in v:
            errs.append(f"validation missing {key}")
    if v.get("status") not in {"pass", "warn", "fail", "partial"}:
        errs.append(f"bad validation.status {v.get('status')}")
    if not isinstance(v.get("checks"), list):
        errs.append("validation.checks is not a list")
    else:
        for c in v["checks"]:
            if not isinstance(c, dict) or not {"id", "status", "detail"} <= set(c):
                errs.append(f"bad check {c!r}")
    c = payload["confidence"]
    if not isinstance(c, dict):
        return errs + ["confidence is not an object"]
    for key in ("level", "basis", "uncertain"):
        if key not in c:
            errs.append(f"confidence missing {key}")
    if c.get("level") not in {"high", "medium", "low"}:
        errs.append(f"bad confidence.level {c.get('level')}")
    for key in ("basis", "uncertain"):
        if not isinstance(c.get(key), list):
            errs.append(f"confidence.{key} is not a list")
    return errs


def write_case_md(case: dict, payload: dict, result: dict, elapsed: float, env_path: Path, kind: str) -> None:
    outdir = SAMPLES / case["tool"]
    outdir.mkdir(parents=True, exist_ok=True)
    name = f"{'CASE' if kind == 'sample' else 'NEGATIVE'}_{case['id']}.md"
    args_json = json.dumps(case["args"], ensure_ascii=False)
    cmd_parts = []
    for key, value in case["args"].items():
        if isinstance(value, list):
            value = ",".join(str(v) for v in value)
        elif isinstance(value, bool):
            value = "true" if value else "false"
        text = str(value).replace("\\", "/")
        if " " in text:
            text = '"' + text + '"'
        cmd_parts.append(f"--{key} {text}")
    call_cmd = "python tests/call_one.py " + case["tool"] + " " + " ".join(cmd_parts)
    checks = payload.get("validation", {}).get("checks", [])
    engine = payload.get("validation", {}).get("engine", {})
    artifacts = payload.get("result", {}).get("artifacts", {})
    log_files = sorted(LOGS.glob(f"{case['tool']}_*.json"), key=lambda p: p.stat().st_mtime)
    latest_log = str(log_files[-1]) if log_files else "(见 logs/server.jsonl)"
    lines = [
        f"# {case['tool']} — {kind} #{case['id']}",
        "",
        f"- 输入：`{case['args']}`",
        f"- 调用：`{call_cmd}`（在安装目录下）",
        f"- 结果：isError={result.get('isError')}，validation={payload.get('validation', {}).get('status')}，confidence={payload.get('confidence', {}).get('level')}",
        f"- 耗时：{elapsed:.2f}s（服务端记录见 `logs/`）",
        f"- 引擎退出码：{engine.get('exit_code')}",
        f"- 信封：`{env_path}`",
        f"- 调用日志：`{latest_log}`（服务端退出码见 `logs/test_summary.json`）",
        "",
        "## 校验项",
        "",
        "| id | status | detail |",
        "|---|---|---|",
    ]
    for c in checks:
        lines.append(f"| {c.get('id')} | {c.get('status')} | {str(c.get('detail', '')).replace('|', '/')} |")
    lines += ["", "## 结果要点", ""]
    res = payload.get("result", {})
    model = res.get("audiveris_model") or {}
    log = res.get("log") or {}
    for key, value in [
        ("note_count", res.get("note_count")),
        ("measure_count", res.get("measure_count")),
        ("page_count", res.get("page_count")),
        ("audiveris_head_count", model.get("head_count")),
        ("audiveris_log_measures", log.get("raw_measures")),
        ("duration_sec", res.get("duration_sec")),
        ("sample_rate", res.get("sample_rate")),
        ("channels", res.get("channels")),
        ("source_type", res.get("source_type")),
        ("error_code", res.get("error_code")),
        ("error", res.get("error")),
    ]:
        if value is not None:
            lines.append(f"- {key}: `{value}`")
    lines += ["", "## 产物", ""]
    if artifacts:
        for k, v in artifacts.items():
            if isinstance(v, list):
                for item in v:
                    lines.append(f"- {k}: `{item}`")
            elif v:
                lines.append(f"- {k}: `{v}`")
    else:
        lines.append("- （无文件产物）")
    lines.append("")
    (outdir / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def severe_count(payload: dict) -> int:
    r = payload.get("result", {})
    if isinstance(r.get("severe"), int):
        return r["severe"]
    n = 0
    for f in r.get("findings", []) or []:
        if f.get("sev") == "严重":
            n += 1
    return n


def main() -> int:
    LOGS.mkdir(parents=True, exist_ok=True)
    srv = Server()
    started = time.time()
    rows = []
    failures = []

    try:
        srv.send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {"name": "e1-selftest", "version": "0.1"},
                },
            }
        )
        init = srv.recv()
        if init.get("id") != 1 or "result" not in init:
            failures.append(f"initialize failed: {init}")
        srv.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        srv.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listing = srv.recv()
        tools = listing.get("result", {}).get("tools", [])
        names = [t.get("name") for t in tools]
        if names != EXPECTED_TOOLS:
            failures.append(f"tools/list mismatch: {names}")
        for t in tools:
            if "inputSchema" not in t or "outputSchema" not in t:
                failures.append(f"{t.get('name')} missing schema")

        for case in TOOL_CASES + NEGATIVE_CASES:
            srv.send(
                {
                    "jsonrpc": "2.0",
                    "id": case["id"],
                    "method": "tools/call",
                    "params": {"name": case["tool"], "arguments": case["args"]},
                }
            )
            t0 = time.time()
            resp = srv.recv()
            elapsed = round(time.time() - t0, 2)
            if resp.get("id") != case["id"]:
                failures.append(f"{case['tool']}: response id {resp.get('id')} != {case['id']}")
                continue
            if "error" in resp:
                failures.append(f"{case['tool']}: JSON-RPC error {resp['error']}")
                continue
            result = resp["result"]
            payload = result.get("structuredContent")
            if not isinstance(payload, dict):
                failures.append(f"{case['tool']}: no structuredContent")
                continue
            errs = envelope_errors(payload)
            if errs:
                failures.extend(f"{case['tool']}: {e}" for e in errs)

            expect = case["expect"]
            if result.get("isError") != expect["is_error"]:
                failures.append(
                    f"{case['tool']}: isError {result.get('isError')} != {expect['is_error']}"
                )
            status = payload.get("validation", {}).get("status")
            if "status_in" in expect and status not in expect["status_in"]:
                failures.append(f"{case['tool']}: status {status} not in {expect['status_in']}")
            if "min_severe" in expect and severe_count(payload) < expect["min_severe"]:
                failures.append(f"{case['tool']}: severe {severe_count(payload)} < {expect['min_severe']}")
            if "error_code" in expect:
                code = payload.get("result", {}).get("error_code")
                if code != expect["error_code"]:
                    failures.append(f"{case['tool']}: error_code {code} != {expect['error_code']}")
            res = payload.get("result", {})
            if "note_count_equals" in expect and res.get("note_count") != expect["note_count_equals"]:
                failures.append(f"{case['tool']}: note_count {res.get('note_count')} != {expect['note_count_equals']}")
            if "head_count_equals" in expect:
                heads = (res.get("audiveris_model") or {}).get("head_count")
                if heads != expect["head_count_equals"]:
                    failures.append(f"{case['tool']}: head_count {heads} != {expect['head_count_equals']}")
            if "min_measures" in expect and (res.get("measure_count") or 0) < expect["min_measures"]:
                failures.append(f"{case['tool']}: measure_count {res.get('measure_count')} < {expect['min_measures']}")
            if "channels_equals" in expect and res.get("channels") != expect["channels_equals"]:
                failures.append(f"{case['tool']}: channels {res.get('channels')} != {expect['channels_equals']}")
            if "sample_rate_equals" in expect and res.get("sample_rate") != expect["sample_rate_equals"]:
                failures.append(f"{case['tool']}: sample_rate {res.get('sample_rate')} != {expect['sample_rate_equals']}")
            if "min_duration" in expect and (res.get("duration_sec") or 0) < expect["min_duration"]:
                failures.append(f"{case['tool']}: duration {res.get('duration_sec')} < {expect['min_duration']}")
            if "min_note_count" in expect and (res.get("note_count") or 0) < expect["min_note_count"]:
                failures.append(f"{case['tool']}: note_count {res.get('note_count')} < {expect['min_note_count']}")
            if "source_type" in expect and res.get("source_type") != expect["source_type"]:
                failures.append(f"{case['tool']}: source_type {res.get('source_type')} != {expect['source_type']}")

            outdir = SAMPLES / case["tool"]
            outdir.mkdir(parents=True, exist_ok=True)
            case_tag = "negative" if case in NEGATIVE_CASES else "sample"
            env_path = outdir / f"{case_tag}_{case['id']}_envelope.json"
            env_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
            write_case_md(case, payload, result, elapsed, env_path, case_tag)
            rows.append(
                {
                    "id": case["id"],
                    "tool": case["tool"],
                    "kind": case_tag,
                    "is_error": result.get("isError"),
                    "validation_status": status,
                    "confidence": payload.get("confidence", {}).get("level"),
                    "elapsed_s": elapsed,
                    "envelope": str(env_path),
                }
            )
            print(
                f"[{case['id']}] {case['tool']:<20} kind={case_tag:<8} "
                f"isError={result.get('isError')!s:<5} status={status:<7} "
                f"conf={payload.get('confidence', {}).get('level')} {elapsed:.2f}s"
            )

        # unknown tool must be a JSON-RPC -32602 error
        srv.send(
            {
                "jsonrpc": "2.0",
                "id": 299,
                "method": "tools/call",
                "params": {"name": "no_such_tool", "arguments": {}},
            }
        )
        unknown = srv.recv()
        code = unknown.get("error", {}).get("code")
        if code != -32602:
            failures.append(f"unknown tool returned {unknown}")
        print(f"[299] unknown tool -> error {code}")

    finally:
        exit_code = srv.close()

    main_rows = [r for r in rows if r["kind"] == "sample"]
    neg_rows = [r for r in rows if r["kind"] == "negative"]
    original_six = [r for r in rows if 101 <= r["id"] <= 106]
    summary = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "server": str(SERVER),
        "server_exit_code": exit_code,
        "elapsed_s": round(time.time() - started, 2),
        "main_cases": len(main_rows),
        "negative_cases": len(neg_rows),
        "original_six_cases": len(original_six),
        "original_six_ok": len(original_six) == 6 and all(r["is_error"] is False for r in original_six),
        "all_ok": not failures,
        "failures": failures,
        "rows": rows,
        "stderr_log": str(LOGS / "test_server_stderr.txt"),
    }
    (LOGS / "test_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print("\n" + json.dumps({k: summary[k] for k in ("all_ok", "main_cases", "negative_cases", "original_six_ok", "server_exit_code", "elapsed_s")}, ensure_ascii=False))
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
