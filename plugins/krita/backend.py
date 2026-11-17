"""Krita session over the dccmcp_bridge plugin running inside Krita (see bridge/)."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

DEFAULT_EXE = r"C:\Program Files\Krita (x64)\bin\krita.exe"


class KritaError(RuntimeError):
    pass


def state_file() -> Path:
    """Same rule as bridge/dccmcp_bridge/commands.py:state_file (the bridge cannot import us)."""
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "krita" / "dccmcp_bridge.json"
    return Path.home() / ".local" / "share" / "krita" / "dccmcp_bridge.json"


class KritaBackend:
    name = "krita"

    def __init__(self, cfg: dict, launch: Callable[[list[str]], Any] | None = None) -> None:
        self.cfg = cfg
        self.default_mode = cfg.get("default_mode", "live")
        self.state_path = Path(cfg["state_file"]) if cfg.get("state_file") else state_file()
        self._launch = launch or (lambda argv: subprocess.Popen(argv))
        self.sock: socket.socket | None = None
        self.token = ""
        self._buf = b""
        self._next_id = 0
        self._handlers: list = []

    # --- Backend v1 ---
    def start(self, mode: str) -> dict:
        if mode != "live":
            raise ValueError("krita supports only mode 'live' for now (an open Krita window)")
        info = self._connect()
        if info is None:
            exe = self.cfg.get("exe", DEFAULT_EXE)
            if not Path(exe).exists():
                raise KritaError(f"Krita not found at {exe}; set [krita] exe in dcc_mcp.toml")
            self._launch([exe, "--nosplash"])
            deadline = time.monotonic() + float(self.cfg.get("start_timeout", 90))
            while info is None and time.monotonic() < deadline:
                time.sleep(0.5)
                info = self._connect()
            if info is None:
                raise KritaError("Krita started but the DCC-MCP bridge does not answer: run "
                                 "'python -m plugins.krita.install' with Krita closed, or enable "
                                 "'DCC-MCP Bridge' in Settings > Python Plugin Manager and restart Krita")
        return {"version": info["krita"], "port": self.sock.getpeername()[1]}

    def stop(self) -> None:
        # only disconnect: the window may hold unsaved work done by hand
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def health(self) -> bool:
        try:
            self.call("ping")
            return True
        except Exception:
            return False

    def capabilities(self) -> set[str]:
        return {"paint", "ui"}

    def subscribe(self, handler) -> None:
        self._handlers.append(handler)

    # --- used by operations ---
    def call(self, cmd: str, args: dict | None = None) -> Any:
        """Send one command to the bridge; KritaError carries the bridge's message."""
        if self.sock is None:
            raise KritaError("Krita session is not running")
        self._next_id += 1
        req = {"id": self._next_id, "token": self.token, "cmd": cmd, "args": args or {}}
        try:
            self.sock.settimeout(float(self.cfg.get("call_timeout", 300)))
            self.sock.sendall(json.dumps(req, ensure_ascii=False).encode("utf-8") + b"\n")
            reply = json.loads(self._read_line())
        except (OSError, ValueError) as e:
            self.stop()
            self._emit("lost", {"command": cmd})
            raise KritaError(f"lost connection to Krita during {cmd!r}: {e}") from e
        if not reply.get("ok"):
            raise KritaError(reply.get("error", "bridge error"))
        return reply.get("result")

    # --- internals ---
    def _connect(self) -> dict | None:
        """Connect to the bridge if its state file points at a live one with a window; else None."""
        self.stop()
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.sock = socket.create_connection(("127.0.0.1", int(state["port"])), timeout=2)
        except (OSError, ValueError, KeyError):
            self.sock = None
            return None
        self.token, self._buf = state.get("token", ""), b""
        try:
            info = self.call("ping")
        except KritaError:
            return None
        return info if info.get("window") else None  # opening documents needs the main window

    def _read_line(self) -> bytes:
        while b"\n" not in self._buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise OSError("bridge closed the connection")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line

    def _emit(self, event: str, data: dict) -> None:
        for handler in self._handlers:
            handler(event, data)
