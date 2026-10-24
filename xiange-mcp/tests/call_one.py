# -*- coding: utf-8 -*-
"""Call one MCP tool once, for reproducible samples.

Usage (either form):
    python tests/call_one.py <tool_name> --score_path "D:/.../x.musicxml"
    python tests/call_one.py <tool_name> '<json arguments>'

Examples:
    python tests/call_one.py check_notation --score_path samples/shared/ode_excerpt.musicxml
    python tests/call_one.py render_score --score_path samples/shared/ode_excerpt.musicxml --formats pdf,png

Exit code: 0 if the tool returned isError=false, 1 otherwise.
The full envelope is printed to stdout and saved under logs/.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "server" / "server.py"
LOGS = ROOT / "logs"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    tool = sys.argv[1]
    rest = sys.argv[2:]
    if len(rest) == 1 and rest[0].lstrip().startswith("{"):
        args = json.loads(rest[0])
    else:
        args = {}
        i = 0
        while i < len(rest):
            key = rest[i]
            if not key.startswith("--") or i + 1 >= len(rest):
                print(f"bad argument near {key!r}; use --key value or one JSON object", file=sys.stderr)
                return 2
            name, raw = key[2:], rest[i + 1]
            i += 2
            if name == "formats":
                args[name] = [x.strip() for x in raw.split(",") if x.strip()]
            elif raw.lower() in ("true", "false"):
                args[name] = raw.lower() == "true"
            else:
                try:
                    args[name] = int(raw)
                except ValueError:
                    try:
                        args[name] = float(raw)
                    except ValueError:
                        args[name] = raw
    LOGS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    stderr_path = LOGS / f"call_one_{tool}_{stamp}.stderr.txt"
    with open(stderr_path, "wb") as errf:
        proc = subprocess.Popen(
            [sys.executable, str(SERVER)],
            cwd=str(ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errf,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        assert proc.stdin is not None and proc.stdout is not None

        def send(obj: dict) -> None:
            proc.stdin.write(json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n")
            proc.stdin.flush()

        def recv() -> dict:
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError("server closed stdout")
            return json.loads(line.decode("utf-8"))

        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            }
        )
        recv()
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool, "arguments": args},
            }
        )
        resp = recv()
        send({"jsonrpc": "2.0", "method": "exit"})
        try:
            proc.stdin.close()
        except Exception:
            pass
        proc.wait(timeout=15)

    if "error" in resp:
        print(json.dumps(resp, ensure_ascii=False, indent=1))
        return 1
    payload = resp.get("result", {}).get("structuredContent", {})
    out_path = LOGS / f"call_one_{tool}_{stamp}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=1))
    print(f"\n[saved] {out_path}", file=sys.stderr)
    print(f"[stderr] {stderr_path}", file=sys.stderr)
    return 0 if not resp.get("result", {}).get("isError") else 1


if __name__ == "__main__":
    raise SystemExit(main())
