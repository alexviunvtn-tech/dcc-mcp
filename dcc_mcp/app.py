from __future__ import annotations

import importlib
import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .assets import AssetStore
from .registry import Registry
from .runner import Runner


@dataclass
class Core:
    registry: Registry
    assets: AssetStore
    runner: Runner


def build_core(config_path: str | Path) -> Core:
    config_path = Path(config_path).resolve()
    root = config_path.parent
    cfg = tomllib.loads(config_path.read_text(encoding="utf-8"))

    # 'plugins' is a namespace package: every plugin_paths entry may hold plugins/<name>/
    for folder in [root, *(root / p for p in cfg.get("plugin_paths", []))]:
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))

    registry = Registry()
    for name in cfg.get("plugins", []):
        importlib.import_module(f"plugins.{name}").register(registry, cfg.get(name, {}))
    registry.load_recipes(root / cfg.get("recipes_dir", "recipes"))

    # an installed extension lives in the app's folder, so asset versions go to a folder the user picked
    assets = AssetStore(Path(os.environ.get("DCC_MCP_WORK_DIR") or root / cfg.get("work_dir", "work")))
    return Core(registry, assets, Runner(registry, assets))
