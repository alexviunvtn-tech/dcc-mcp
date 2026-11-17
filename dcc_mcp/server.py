from __future__ import annotations

import json
from pathlib import Path

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from .app import Core
from .assets import AssetError


def build_server(core: Core) -> _Server:
    """The tool list is fixed; new operations reach the model through run_operation."""
    reg, runner, assets = core.registry, core.runner, core.assets
    mcp = _Server("dcc-mcp", instructions=(
        "Drives DCC programs (RizomUV, ZBrush...) through plugins. Import a mesh with import_asset, "
        "then call run_recipe or run_operation. Use describe_operation for an operation's params."))

    @mcp.tool()
    def list_operations(backend: str | None = None) -> list[dict]:
        """Operations by key with a one-line summary."""
        return [{"key": s.key, "kind": s.kind, "summary": s.summary}
                for s in reg.ops.values() if backend in (None, s.backend)]

    @mcp.tool()
    def describe_operation(key: str) -> dict:
        """JSON schema of an operation's params and what it needs."""
        s = reg.ops.get(key)
        if s is None:
            return {"error": f"unknown operation {key!r}"}
        return {"key": s.key, "kind": s.kind, "summary": s.summary,
                "params_schema": s.params_schema, "needs": sorted(s.needs)}

    @mcp.tool()
    def run_operation(key: str, asset: str | None = None, params: dict | None = None) -> dict:
        """Run one operation. asset = 'name' (latest version) or 'name@v002'."""
        return runner.run_op(key, asset, params)

    @mcp.tool()
    def list_recipes() -> dict:
        """Recipes: their steps and default params."""
        return {n: {"params": r.get("params", {}),
                    "steps": [s.get("op") or s.get("check") for s in r["steps"]]}
                for n, r in reg.recipes.items()}

    @mcp.tool()
    def run_recipe(name: str, asset: str, overrides: dict | None = None) -> dict:
        """Run a recipe on an asset; overrides replace the recipe's params."""
        return runner.run_recipe(name, asset, overrides)

    @mcp.tool()
    def start_session(backend: str, mode: str | None = None) -> dict:
        """Start or switch a program: mode 'live' (window) or 'headless' for RizomUV."""
        try:
            runner.sessions.start(backend, mode)
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}
        return runner.sessions.status()

    @mcp.tool()
    def stop_session(backend: str) -> dict:
        """Close a program (e.g. backend='rizom'). Unsaved work in it is lost: save first."""
        state = runner.sessions.status().get(backend, {}).get("state")
        if state is None:
            return {"error": f"{backend!r} is not running"}
        if state == "busy":
            return {"error": f"{backend!r} is busy with a call; stop it after the call ends"}
        runner.sessions.stop(backend)
        return runner.sessions.status()

    @mcp.tool()
    def session_status() -> dict:
        """State of every running program."""
        return runner.sessions.status()

    @mcp.tool()
    def import_asset(name: str, path: str) -> dict:
        """Copy a mesh file into work/<name>/ as version v001."""
        try:
            return assets.import_file(name, Path(path))
        except AssetError as e:
            return {"error": str(e)}

    @mcp.tool()
    def asset_history(asset: str) -> dict:
        """Versions and the log of operations run on an asset."""
        try:
            return assets.info(asset)
        except AssetError as e:
            return {"error": str(e)}

    for spec in reg.ops.values():
        if spec.featured:
            mcp.add_tool(_featured(runner, spec.key), name=spec.key.replace(".", "_"),
                         description=f"{spec.summary} Params: {json.dumps(spec.params_schema)}")
    return mcp


def _featured(runner, key: str):
    def tool(asset: str | None = None, params: dict | None = None) -> dict:
        return runner.run_op(key, asset, params)
    return tool
