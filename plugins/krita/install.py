"""Put the bridge into Krita and switch it on. Run with Krita closed: python -m plugins.krita.install"""
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

BRIDGE = Path(__file__).resolve().parent / "bridge"
NAME = "dccmcp_bridge"


def krita_dirs() -> tuple[Path, Path]:
    """(pykrita folder, kritarc file) for the current user."""
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "krita" / "pykrita", Path(os.environ["LOCALAPPDATA"]) / "kritarc"
    return Path.home() / ".local/share/krita/pykrita", Path.home() / ".config/kritarc"


def enable_in_kritarc(text: str, name: str = NAME) -> str:
    """Set [python] enable_<name>=true, touching nothing else (kritarc is not plain INI: keep it as text)."""
    key = f"enable_{name}=true"
    lines = text.splitlines()
    try:
        start = lines.index("[python]")
    except ValueError:
        return text.rstrip("\n") + ("\n\n" if text.strip() else "") + f"[python]\n{key}\n"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    for i in range(start + 1, end):
        if re.fullmatch(rf"enable_{re.escape(name)}\s*=.*", lines[i]):
            lines[i] = key
            break
    else:
        lines.insert(start + 1, key)
    return "\n".join(lines) + "\n"


def install(pykrita: Path, kritarc: Path) -> None:
    pykrita.mkdir(parents=True, exist_ok=True)
    shutil.copytree(BRIDGE / NAME, pykrita / NAME, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(BRIDGE / f"{NAME}.desktop", pykrita / f"{NAME}.desktop")
    old = kritarc.read_text(encoding="utf-8") if kritarc.exists() else ""
    if old:
        shutil.copy2(kritarc, kritarc.with_name(kritarc.name + ".bak"))
    kritarc.write_text(enable_in_kritarc(old), encoding="utf-8")


def main() -> None:
    pykrita, kritarc = krita_dirs()
    install(pykrita, kritarc)
    print(f"bridge copied to {pykrita / NAME}\nenabled in {kritarc} (backup: {kritarc.name}.bak)\n"
          "Start Krita. If the bridge does not answer, enable 'DCC-MCP Bridge' in "
          "Settings > Configure Krita > Python Plugin Manager and restart Krita.")


if __name__ == "__main__":
    main()
