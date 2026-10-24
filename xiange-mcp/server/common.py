# -*- coding: utf-8 -*-
"""Shared helpers for the E1 music MCP server (stage 1).

No third-party dependencies on the Windows host.  Engines that need music21,
OpenCV or basic-pitch run inside the local WSL distro; this module only handles
paths, envelopes, logging and small file operations.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = ROOT / "server"
SAMPLES_DIR = ROOT / "samples"
LOGS_DIR = ROOT / "logs"
SCHEMAS_DIR = SERVER_DIR / "schemas"

# Every absolute location is supplied by the installer through an environment
# variable; the defaults are relative to this package or to PATH.  See README.
MUSIC_PACK = Path(os.environ.get("E1_MUSIC_PACK", str(ROOT / "music-pack"))).expanduser()
MUSIC_TOOLS = MUSIC_PACK / "tools"

ENGINE_PATHS = {
    "theory": MUSIC_TOOLS / "theory_check.py",
    "notation": MUSIC_TOOLS / "notation_check.py",
    "router": MUSIC_TOOLS / "工具_谱种路由.py",
}

LILYPOND = Path(os.environ.get("E1_LILYPOND", "lilypond")).expanduser()
WSL_DISTRO = os.environ.get("E1_WSL_DISTRO", "Ubuntu-24.04")

# WSL-side engine paths (not Windows paths; resolved inside the distro).
AUDIVERIS_APP = os.environ.get(
    "E1_AUDIVERIS_APP", "/opt/audiveris/opt/audiveris/bin/Audiveris"
)
AUDIVERIS_PREFIX = os.environ.get("E1_AUDIVERIS_PREFIX", "/opt/audiveris")
ENGINE_DEPS = os.environ.get("E1_ENGINE_DEPS", "/opt/e1-mcp/engine_deps")

SERVER_NAME = "e1-music-mcp"
SERVER_VERSION = "0.2.0"


class ToolError(Exception):
    """A user-visible tool failure; carries a stable code and optional detail."""

    def __init__(self, message: str, code: str = "tool_error", detail: Any = None):
        super().__init__(message)
        self.code = code
        self.detail = detail


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def new_run_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_file(value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"{field} 必须是非空字符串路径", code="invalid_argument")
    p = Path(value).expanduser()
    try:
        p = p.resolve()
    except OSError as exc:
        raise ToolError(f"{field} 路径无法解析：{value}（{exc}）", code="invalid_path") from exc
    if not p.is_file():
        raise ToolError(f"{field} 指向的文件不存在：{p}", code="input_not_found")
    return p


def resolve_outdir(tool_name: str, value: Any) -> Path:
    """Keep every artifact inside the install directory."""
    if value is None or (isinstance(value, str) and not value.strip()):
        out = SAMPLES_DIR / tool_name
    else:
        if not isinstance(value, str):
            raise ToolError("output_dir 必须是字符串路径", code="invalid_argument")
        out = Path(value).expanduser()
        try:
            out = out.resolve()
        except OSError as exc:
            raise ToolError(f"output_dir 无法解析：{value}（{exc}）", code="invalid_path") from exc
        try:
            out.relative_to(ROOT)
        except ValueError as exc:
            raise ToolError(
                f"output_dir 必须位于安装目录 {ROOT} 之下；收到 {out}", code="output_outside_root"
            ) from exc
    out.mkdir(parents=True, exist_ok=True)
    return out


def write_bytes(dest: Path, data: bytes) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as fh:
        fh.write(data)
    return dest


def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, obj: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    return path


def check(cid: str, status: str, detail: str, **extra: Any) -> dict:
    item = {"id": cid, "status": status, "detail": detail}
    item.update(extra)
    return item


def envelope(
    result: dict,
    checks: list[dict],
    level: str,
    basis: list[str],
    uncertain: list[str],
    engine: dict | None = None,
) -> dict:
    """Build the fixed three-piece payload used by every tool."""
    if any(c.get("status") == "fail" for c in checks):
        status = "fail"
    elif any(c.get("status") == "warn" for c in checks):
        status = "warn"
    elif any(c.get("status") == "skip" for c in checks):
        status = "partial"
    else:
        status = "pass"
    return {
        "result": result,
        "validation": {
            "status": status,
            "checks": checks,
            "engine": engine or {},
        },
        "confidence": {
            "level": level,
            "basis": basis,
            "uncertain": uncertain,
        },
    }


def error_envelope(tool: str, exc: Exception) -> dict:
    code = exc.code if isinstance(exc, ToolError) else "unhandled_error"
    detail = exc.detail if isinstance(exc, ToolError) else None
    msg = str(exc) or exc.__class__.__name__
    return envelope(
        {"tool": tool, "error": msg, "error_code": code, "detail": detail},
        [check("execution", "fail", msg, error_code=code)],
        "low",
        [],
        [msg],
        {"tool": tool, "status": "error"},
    )


def log_call(tool: str, run_id: str, record: dict) -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    path = LOGS_DIR / f"{tool}_{run_id}.json"
    write_json(path, record)
    with open(LOGS_DIR / "server.jsonl", "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def engine_info(name: str, path: Path | None = None, extra: dict | None = None) -> dict:
    info = {"name": name}
    if path is not None:
        info["path"] = str(path)
        info["exists"] = path.is_file()
    if extra:
        info.update(extra)
    return info


def check_public_inputs() -> dict:
    """Startup self-check used by tools/list and the README."""
    return {
        "engines": {k: {"path": str(v), "exists": v.is_file()} for k, v in ENGINE_PATHS.items()},
        "lilypond": {"path": str(LILYPOND), "exists": LILYPOND.is_file()},
        "wsl_engines": {
            "audiveris_app": AUDIVERIS_APP,
            "audiveris_prefix": AUDIVERIS_PREFIX,
            "engine_deps": ENGINE_DEPS,
            "note": "WSL-side paths; existence is checked inside the distro at call time",
        },
        "host_python": os.sys.version.split()[0],
        "wsl_distro": WSL_DISTRO,
    }
