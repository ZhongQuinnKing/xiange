#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E1 Music MCP server (stage 1).

Stdio JSON-RPC 2.0 / MCP.  Eight tools, fixed result/validation/confidence
envelope, local engines only.

Start:
    python server/server.py

The process writes JSON-RPC messages to stdout and diagnostics to stderr.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
ROOT = SERVER_DIR.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import common  # noqa: E402
import tools_impl  # noqa: E402

SCHEMAS = SERVER_DIR / "schemas"


def log_stderr(msg: str) -> None:
    sys.stderr.write(f"[e1-music-mcp] {msg}\n")
    sys.stderr.flush()


def read_message() -> tuple[dict | None, str]:
    """Read one JSON-RPC message; support newline and Content-Length framing."""
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None, "newline"
        if not line.strip():
            continue
        if line.lower().startswith(b"content-length:"):
            try:
                length = int(line.split(b":", 1)[1].strip())
            except (IndexError, ValueError):
                raise ValueError("invalid Content-Length header")
            while True:
                header = sys.stdin.buffer.readline()
                if header in (b"\r\n", b"\n", b""):
                    break
            data = sys.stdin.buffer.read(length)
            return json.loads(data.decode("utf-8")), "content-length"
        try:
            return json.loads(line.decode("utf-8")), "newline"
        except json.JSONDecodeError:
            # A message may be pretty-printed across lines by a client; try to
            # accumulate until it parses.
            buf = line
            while True:
                more = sys.stdin.buffer.readline()
                if not more:
                    break
                buf += more
                try:
                    return json.loads(buf.decode("utf-8")), "newline"
                except json.JSONDecodeError:
                    continue
            raise


def send_message(obj: dict, framing: str) -> None:
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if framing == "content-length":
        out = b"Content-Length: %d\r\n\r\n" % len(data) + data
    else:
        out = data + b"\n"
    sys.stdout.buffer.write(out)
    sys.stdout.buffer.flush()


def error_response(mid, code: int, message: str, data=None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": mid, "error": err}


TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def validate_arguments(schema: dict, args: dict) -> None:
    if not isinstance(args, dict):
        raise common.ToolError("arguments 必须是对象", code="invalid_arguments")
    props = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in args:
            raise common.ToolError(f"缺少必填参数：{key}", code="invalid_arguments")
    if schema.get("additionalProperties") is False:
        unknown = sorted(set(args) - set(props))
        if unknown:
            raise common.ToolError(f"未知参数：{', '.join(unknown)}", code="invalid_arguments")
    for key, value in args.items():
        rule = props.get(key)
        if not rule:
            continue
        expected = rule.get("type")
        if expected:
            py_type = TYPE_MAP[expected]
            if expected in {"integer", "number"} and isinstance(value, bool):
                raise common.ToolError(f"{key} 必须是数字", code="invalid_arguments")
            if not isinstance(value, py_type):
                raise common.ToolError(
                    f"{key} 类型应为 {expected}，收到 {type(value).__name__}",
                    code="invalid_arguments",
                )
        enum = rule.get("enum")
        if enum and value not in enum:
            raise common.ToolError(f"{key} 必须是 {enum} 之一", code="invalid_arguments")


def load_schema(name: str) -> dict:
    with open(SCHEMAS / name, "r", encoding="utf-8") as fh:
        return json.load(fh)


def tool_list() -> list[dict]:
    output_schema = load_schema("common.output.json")
    tools = []
    for spec in tools_impl.TOOL_SPECS:
        tools.append(
            {
                "name": spec["name"],
                "title": spec["title"],
                "description": spec["description"],
                "inputSchema": load_schema(spec["input"]),
                "outputSchema": output_schema,
            }
        )
    return tools


def call_tool(name: str, args: dict) -> dict:
    started = time.time()
    spec = next((s for s in tools_impl.TOOL_SPECS if s["name"] == name), None)
    if spec is None:
        raise common.ToolError(f"未知工具：{name}", code="unknown_tool")
    schema = load_schema(spec["input"])
    validate_arguments(schema, args)
    handler = tools_impl.TOOL_HANDLERS[name]
    try:
        payload = handler(args)
        is_error = payload.get("validation", {}).get("status") == "fail"
    except common.ToolError as exc:
        payload = common.error_envelope(name, exc)
        is_error = True
    except Exception as exc:  # noqa: BLE001
        log_stderr("unhandled error:\n" + traceback.format_exc())
        payload = common.error_envelope(name, exc)
        is_error = True

    elapsed = round((time.time() - started) * 1000, 1)
    run_id = common.new_run_id()
    record = {
        "ts": common.now_iso(),
        "run_id": run_id,
        "tool": name,
        "arguments": args,
        "is_error": is_error,
        "validation_status": payload.get("validation", {}).get("status"),
        "confidence": payload.get("confidence", {}).get("level"),
        "elapsed_ms": elapsed,
        "payload": payload,
    }
    try:
        common.log_call(name, run_id, record)
    except Exception as exc:  # logging must not break the call
        log_stderr(f"log write failed: {exc}")

    text = json.dumps(payload, ensure_ascii=False, indent=1)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": payload,
        "isError": is_error,
    }


def handle(req: dict) -> dict | None:
    method = req.get("method")
    mid = req.get("id")
    params = req.get("params") or {}
    is_notification = "id" not in req

    if method == "initialize":
        requested = params.get("protocolVersion")
        supported = {"2024-11-05", "2025-03-26", "2025-06-18"}
        version = requested if requested in supported else "2024-11-05"
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": common.SERVER_NAME,
                    "version": common.SERVER_VERSION,
                    "title": "E1 Music MCP",
                },
                "instructions": (
                    "八个音乐工具：谱种路由、音符级 OMR（Audiveris）、音频/视频转谱、"
                    "音轨提取（PyAV）、乐理校验、记谱规范校验、格式互转与移调、"
                    "渲染出图与 PDF。所有工具返回固定三件套 result / validation / "
                    "confidence。所有引擎均在本地运行，不访问外部服务。"
                ),
            },
        }
    if is_notification:
        if method == "notifications/initialized":
            log_stderr("client initialized")
        elif method == "exit":
            return "EXIT"
        elif method in {"notifications/cancelled", "notifications/roots/list_changed"}:
            pass
        else:
            log_stderr(f"notification ignored: {method}")
        return None

    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": tool_list()}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(name, str):
            return error_response(mid, -32602, "tools/call 缺少 name")
        try:
            result = call_tool(name, args)
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except common.ToolError as exc:
            return error_response(mid, -32602, str(exc), {"code": exc.code})
    if method in {"resources/list", "resources/templates/list"}:
        key = "resources" if method == "resources/list" else "resourceTemplates"
        return {"jsonrpc": "2.0", "id": mid, "result": {key: []}}
    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"prompts": []}}
    if method == "logging/setLevel":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "shutdown":
        return {"jsonrpc": "2.0", "id": mid, "result": None}
    return error_response(mid, -32601, f"method not found: {method}")


def main() -> int:
    log_stderr(f"ready pid={os.getpid()} python={sys.version.split()[0]}")
    log_stderr(json.dumps(common.check_public_inputs(), ensure_ascii=False))
    while True:
        try:
            req, framing = read_message()
        except Exception as exc:  # parse error
            send_message(error_response(None, -32700, f"parse error: {exc}"), "newline")
            continue
        if req is None:
            break
        if isinstance(req, list):
            responses = []
            for item in req:
                try:
                    res = handle(item)
                    if res == "EXIT":
                        break
                    if res is not None:
                        responses.append(res)
                except Exception as exc:  # noqa: BLE001
                    log_stderr("request error:\n" + traceback.format_exc())
                    responses.append(error_response(item.get("id"), -32603, str(exc)))
            if responses:
                send_message(responses, framing)
            continue
        try:
            res = handle(req)
        except Exception as exc:  # noqa: BLE001
            log_stderr("request error:\n" + traceback.format_exc())
            send_message(error_response(req.get("id"), -32603, str(exc)), framing)
            continue
        if res == "EXIT":
            break
        if res is not None:
            send_message(res, framing)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, BrokenPipeError):
        raise SystemExit(0)
