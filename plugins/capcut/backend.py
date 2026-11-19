"""CapCut 'session': no program to drive, only its draft folders; edits live here until capcut.save."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

from .draft import Draft, DraftError


def default_drafts_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ["LOCALAPPDATA"]) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
    return Path.home() / "Movies" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"


def ffprobe(exe: str) -> Callable[[str], dict]:
    def probe(path: str) -> dict:
        try:
            out = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
                                  "-of", "json", path], capture_output=True, text=True, timeout=60, check=True).stdout
        except FileNotFoundError:
            raise DraftError(f"ffprobe not found ({exe!r}): install ffmpeg or set [capcut] ffprobe in dcc_mcp.toml")
        except subprocess.CalledProcessError as e:
            raise DraftError(f"ffprobe could not read {path}: {e.stderr.strip()}")
        data = json.loads(out)
        streams = data.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), {})
        duration = (data.get("format") or {}).get("duration")
        return {"duration": float(duration) if duration not in (None, "N/A") else None,
                "width": video.get("width"), "height": video.get("height"),
                "has_audio": any(s.get("codec_type") == "audio" for s in streams)}
    return probe


def capcut_running() -> bool:
    if sys.platform != "win32":
        return False
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CapCut.exe", "/NH"], capture_output=True, text=True)
    return "capcut.exe" in out.stdout.lower()


class CapCutBackend:
    name = "capcut"

    def __init__(self, cfg: dict, probe: Callable[[str], dict] | None = None,
                 running: Callable[[], bool] = capcut_running) -> None:
        self.cfg = cfg
        self.default_mode = cfg.get("default_mode", "files")
        self.root = Path(cfg["drafts_dir"]) if cfg.get("drafts_dir") else default_drafts_dir()
        self.probe = probe or ffprobe(cfg.get("ffprobe", "ffprobe"))
        self.running = running
        self.open: dict[str, Draft] = {}  # draft name -> draft with unsaved edits

    # --- Backend v1 ---
    def start(self, mode: str) -> dict:
        if mode != "files":
            raise ValueError("capcut supports only mode 'files': it edits draft folders while CapCut is closed")
        if not self.root.is_dir():
            raise DraftError(f"CapCut drafts folder not found: {self.root}; set [capcut] drafts_dir")
        return {"drafts_dir": str(self.root)}

    def stop(self) -> None:
        self.open.clear()  # unsaved edits are dropped, like closing a program without saving

    def health(self) -> bool:
        return self.root.is_dir()

    def capabilities(self) -> set[str]:
        return {"drafts"}

    def subscribe(self, handler) -> None:
        pass  # nothing edits the drafts behind our back while CapCut is closed; save checks for it

    # --- used by operations ---
    def folder(self, name: str) -> Path:
        folder = (self.root / name).resolve()
        # trust boundary: the name comes from the model; keep it a direct child of the drafts folder
        if folder.parent != self.root.resolve() or not folder.is_dir():
            raise DraftError(f"no draft {name!r} in {self.root}; see capcut.list")
        return folder

    def draft(self, name: str) -> Draft:
        if name not in self.open:
            self.open[name] = Draft(self.folder(name), self.probe, lambda: self.others(name))
        return self.open[name]

    def others(self, name: str) -> list[Path]:
        folders = [p for p in self.root.iterdir() if p.is_dir() and p.name != name and not p.name.startswith(".")]
        return sorted(folders, key=lambda p: p.stat().st_mtime, reverse=True)

    def blockers(self, name: str, force: bool) -> list[str]:
        """Reasons not to write: CapCut autosaves an open draft over our edits."""
        found = []
        if (self.folder(name) / ".locked").exists():
            found.append("the draft is open in CapCut (.locked): close the project first")
        if not force and self.running():
            found.append("CapCut is running: close it, or pass force=true if this draft is not open in it")
        return found
