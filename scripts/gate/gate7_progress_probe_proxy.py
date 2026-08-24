#!/usr/bin/env python3
"""GATE 7 §18 stdio wire-tap for the progress conformance probe.

Spawns the probe MCP server as a child and relays stdio between the client
(Codex) and the server, appending every JSON-RPC frame in both directions to a
wire log. This gives verbatim on-the-wire evidence of whether the client sent a
``progressToken`` and whether ``notifications/progress`` frames were delivered,
rather than inferring it from SDK behaviour.

Disposable discovery tooling. Not production code.

Environment:
    G7_WIRE_LOG  path to append wire frames (JSONL), default /tmp/g7-wire.jsonl
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

WIRE = os.environ.get("G7_WIRE_LOG", "/tmp/g7-wire.jsonl")
SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gate7_progress_probe_server.py")


def wire(direction: str, raw: bytes) -> None:
    text = raw.decode("utf-8", "replace").rstrip("\n")
    rec: dict[str, object] = {"ts": time.time(), "dir": direction, "raw": text}
    try:
        parsed = json.loads(text)
        rec["method"] = parsed.get("method")
        rec["id"] = parsed.get("id")
    except Exception:
        rec["method"] = None
    with open(WIRE, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(rec) + "\n")
        handle.flush()


def pump(src, dst, direction: str) -> None:
    for line in iter(src.readline, b""):
        wire(direction, line)
        try:
            dst.write(line)
            dst.flush()
        except Exception:
            break
    try:
        dst.close()
    except Exception:
        pass


def main() -> None:
    child = subprocess.Popen(
        [sys.executable, SERVER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=None,
        bufsize=0,
    )
    # client -> server
    t1 = threading.Thread(
        target=pump, args=(sys.stdin.buffer, child.stdin, "client->server"), daemon=True
    )
    # server -> client
    t2 = threading.Thread(
        target=pump, args=(child.stdout, sys.stdout.buffer, "server->client"), daemon=True
    )
    t1.start()
    t2.start()
    child.wait()
    t2.join(timeout=2)


if __name__ == "__main__":
    main()
