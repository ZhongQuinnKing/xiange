# -*- coding: utf-8 -*-
"""Run engine scripts inside the local WSL distro.

Why this exists: the Windows host Python is bare (no music21 / OpenCV /
basic-pitch), while the WSL Python has them.  Inputs are staged as base64 over
stdin, so no Windows drive has to be mounted into WSL.  Outputs are read back
through wsl.exe and base64-decoded on the host.
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from common import ToolError, WSL_DISTRO

WSL_EXE = shutil.which("wsl.exe") or os.path.join(
    os.environ.get("SystemRoot", ""), "System32", "wsl.exe"
)
WSL_BASE = "/tmp/e1-mcp-run"


def _run(args: list[str], data: bytes | None = None, timeout: int = 120) -> dict:
    cmd = [WSL_EXE, "-d", WSL_DISTRO, "--"] + args
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as exc:
        raise ToolError(f"找不到 wsl.exe（{WSL_EXE}）", code="wsl_not_found") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(
            f"WSL 引擎超时（>{timeout}s）",
            code="engine_timeout",
            detail={"args": args[-1] if args else ""},
        ) from exc
    return {
        "exit_code": proc.returncode,
        "stdout": proc.stdout.decode("utf-8", "replace"),
        "stderr": proc.stderr.decode("utf-8", "replace"),
        "elapsed_ms": round((time.time() - started) * 1000, 1),
    }


def new_run() -> tuple[str, str]:
    run_id = time.strftime("%Y%m%d_%H%M%S") + "_" + base64.urlsafe_b64encode(
        time.time_ns().to_bytes(8, "little")
    ).decode("ascii").rstrip("=")[-8:]
    run_dir = f"{WSL_BASE}/{run_id}"
    result = _run(["bash", "-lc", f"mkdir -p {run_dir}"], timeout=30)
    if result["exit_code"] != 0:
        raise ToolError(
            "WSL 临时目录创建失败",
            code="wsl_stage_failed",
            detail={"stderr": result["stderr"][-1000:]},
        )
    return run_id, run_dir


def stage_file(run_dir: str, name: str, data: bytes, timeout: int = 60) -> None:
    target = f"{run_dir}/{name}"
    code = (
        "import sys,base64;"
        "open(%r,'wb').write(base64.b64decode(sys.stdin.buffer.read()))" % target
    )
    result = _run(["python3", "-c", code], data=base64.b64encode(data), timeout=timeout)
    if result["exit_code"] != 0:
        raise ToolError(
            f"WSL 输入落盘失败：{name}",
            code="wsl_stage_failed",
            detail={"stderr": result["stderr"][-1000:]},
        )


def run_script(run_dir: str, script: str, timeout: int = 120) -> dict:
    """Run a Python script whose working directory is run_dir.

    The script reads control.json (staged beforehand) and writes its outputs
    into the same directory.
    """
    return _run(
        ["bash", "-lc", f"cd {run_dir} && python3 -"],
        data=script.encode("utf-8"),
        timeout=timeout,
    )


def _read_once(run_dir: str, name: str) -> bytes:
    """Read one file out of the distro as base64; no share mount needed."""
    target = f"{run_dir}/{name}"
    proc = subprocess.run(
        [WSL_EXE, "-d", WSL_DISTRO, "--", "base64", "-w0", target],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if proc.returncode != 0:
        raise OSError(proc.stderr.decode("utf-8", "replace").strip()[-500:])
    return base64.b64decode(proc.stdout)


def read_file(run_dir: str, name: str, wait_s: float = 5.0) -> bytes:
    deadline = time.time() + wait_s
    last: Exception | None = None
    while time.time() < deadline:
        try:
            return _read_once(run_dir, name)
        except (OSError, ValueError) as exc:
            last = exc
            time.sleep(0.15)
    raise ToolError(
        f"读不回引擎产物：{name}",
        code="wsl_output_missing",
        detail={"path": f"{run_dir}/{name}", "last_error": str(last) if last else None},
    )


def read_text(run_dir: str, name: str, wait_s: float = 5.0) -> str:
    return read_file(run_dir, name, wait_s=wait_s).decode("utf-8", "replace")


def read_json(run_dir: str, name: str, wait_s: float = 5.0) -> Any:
    import json

    return json.loads(read_text(run_dir, name, wait_s=wait_s))
