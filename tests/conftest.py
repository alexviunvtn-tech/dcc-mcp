import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).resolve().parent / "fixture"
sys.path.insert(0, str(ROOT))


@pytest.fixture
def core(tmp_path):
    from dcc_mcp.app import build_core

    cfg = tmp_path / "dcc_mcp.toml"
    cfg.write_text(
        f"plugins = ['fake']\nplugin_paths = ['{FIXTURE.as_posix()}']\n"
        f"recipes_dir = '{(FIXTURE / 'recipes').as_posix()}'\nwork_dir = 'work'\n",
        encoding="utf-8")
    mesh = tmp_path / "chair.obj"
    mesh.write_text("v 0 0 0\n", encoding="utf-8")
    c = build_core(cfg)
    c.assets.import_file("chair", mesh)
    return c
