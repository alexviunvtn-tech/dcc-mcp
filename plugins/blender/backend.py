"""Blender session: every call starts `blender -b` with runner.py, so nothing keeps running between calls."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

DEFAULT_EXE = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
RUNNER = Path(__file__).resolve().parent / "runner.py"


class BlenderError(RuntimeError):
    pass


class BlenderBackend:
    name = "blender"

    def __init__(self, cfg: dict, run: Callable[..., Any] | None = None) -> None:
        self.cfg = cfg
        self.default_mode = cfg.get("default_mode", "headless")
        self.exe = cfg.get("exe", DEFAULT_EXE)
        self._run = run or subprocess.run
        self.version: str | None = None

    # --- Backend v1 ---
    def start(self, mode: str) -> dict:
        if mode != "headless":
            raise ValueError("blender supports only mode 'headless' for now (blender -b, no window)")
        if not Path(self.exe).exists():
            raise BlenderError(f"Blender not found at {self.exe}; set [blender] exe in dcc_mcp.toml")
        self.version = self.call("ping")["version"]
        return {"version": self.version, "exe": self.exe}

    def stop(self) -> None:
        self.version = None  # nothing to close: each call was its own process

    def health(self) -> bool:
        return self.version is not None and Path(self.exe).exists()

    def capabilities(self) -> set[str]:
        return {"bpy"}

    def subscribe(self, handler) -> None:
        pass  # no events: no Blender stays open between calls

    # --- used by operations ---
    def call(self, cmd: str, input_path: Path | None = None, output: Path | None = None,
             args: dict | None = None) -> dict:
        """Run one command in a fresh background Blender; BlenderError carries Blender's message."""
        with tempfile.TemporaryDirectory(prefix="dccmcp_blender_") as tmp:
            request, result = Path(tmp) / "request.json", Path(tmp) / "result.json"
            request.write_text(json.dumps({
                "cmd": cmd, "args": args or {},
                "input": str(input_path.resolve()) if input_path else None,
                "output": str(output.resolve()) if output else None}), encoding="utf-8")
            argv = [self.exe, "-b", "--factory-startup", "--python", str(RUNNER), "--", str(request), str(result)]
            try:
                proc = self._run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                 timeout=float(self.cfg.get("call_timeout", 600)))
            except subprocess.TimeoutExpired as e:
                raise BlenderError(f"Blender took longer than {e.timeout:.0f} s on {cmd!r}; "
                                   "raise [blender] call_timeout") from e
            if not result.exists():
                tail = (proc.stderr or proc.stdout or "").strip()[-1500:]
                raise BlenderError(f"Blender exited with code {proc.returncode} before answering {cmd!r}: {tail}")
            reply = json.loads(result.read_text(encoding="utf-8"))
        if not reply.get("ok"):
            raise BlenderError(reply.get("error", "Blender error"))
        return reply["result"]
