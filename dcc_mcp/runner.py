from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .assets import AssetError, AssetStore
from .contract import Ctx, OpResult
from .registry import Registry
from .sessions import Sessions

log = logging.getLogger("dcc_mcp")


def _fail(key: str, notes: str) -> dict:
    return {"key": key, "status": "fail", "metrics": {}, "files": [], "notes": notes}


def _fill(value: Any, params: dict) -> Any:
    """'{name}' as a whole string -> params[name], keeping its type."""
    if isinstance(value, dict):
        return {k: _fill(v, params) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, params) for v in value]
    if isinstance(value, str) and value.startswith("{") and value.endswith("}") and value[1:-1] in params:
        return params[value[1:-1]]
    return value


class Runner:
    def __init__(self, registry: Registry, assets: AssetStore) -> None:
        self.registry = registry
        self.assets = assets
        self.sessions = Sessions(registry, self._on_event)
        self._loaded: dict[str, str] = {}  # backend -> asset it last worked on

    def _on_event(self, backend: str, event: str, data: dict) -> None:
        log.info("%s: %s %s", backend, event, data)
        if event == "changed" and backend in self._loaded:
            self.assets.mark_manual_edit(self._loaded[backend])

    def run_op(self, key: str, asset: str | None = None, params: dict | None = None) -> dict:
        """Template: check params -> session -> capabilities -> run -> new version -> report."""
        spec = self.registry.ops.get(key)
        if spec is None:
            return _fail(key, f"unknown operation {key!r}; see list_operations")
        params = params or {}
        errors = sorted(Draft202012Validator(spec.params_schema).iter_errors(params), key=str)
        if errors:
            return _fail(key, "bad params: " + "; ".join(e.message for e in errors))
        try:
            name, input_path = self.assets.resolve(asset) if asset else (None, None)
            session = self.sessions.ensure(spec.backend)
        except Exception as e:  # programs raise their own types (RizomUVLink: ZEx) when they fail to start
            return _fail(key, f"{type(e).__name__}: {e}")
        missing = spec.needs - session.backend.capabilities()
        if missing:
            return _fail(key, f"{spec.backend} in mode {session.mode!r} lacks {sorted(missing)}")
        if not session.lock.acquire(blocking=False):
            return _fail(key, f"{spec.backend} is busy with another call")

        def new_version_path(ext: str) -> Path:
            if name is None:
                raise AssetError(f"{key} writes a file and needs an asset")
            return self.assets.next_path(name, spec.backend, ext)

        ctx = Ctx(session=session.backend, asset=name, input_path=input_path,
                  new_version_path=new_version_path, log=lambda m: log.info("%s: %s", key, m))
        try:
            session.state = "busy"
            result = spec.run(ctx, params)
        except Exception as e:  # a plugin error must not kill the server
            result = OpResult("fail", notes=f"{type(e).__name__}: {e}")
        finally:
            if session.state == "busy":
                session.state = "ready"
            session.lock.release()

        report = {"key": key, "status": result.status, "metrics": result.metrics,
                  "files": result.files, "notes": result.notes}
        if name:
            self._loaded[spec.backend] = name
            try:
                self.assets.commit(name, result.files, {"key": key, "params": params,
                                                        "input": input_path.name, "status": result.status,
                                                        "metrics": result.metrics})
            except AssetError as e:
                report.update(status="fail", notes=f"{result.notes} {e}".strip())
            if self.assets.info(name)["manual_edit"]:
                report["warning"] = "asset was edited by hand after the last saved version; save it to keep the edit"
        return report

    def run_recipe(self, name: str, asset: str, overrides: dict | None = None) -> dict:
        recipe = self.registry.recipes.get(name)
        if recipe is None:
            return {"recipe": name, "status": "fail", "steps": [], "notes": f"unknown recipe {name!r}"}
        values = {**recipe.get("params", {}), **(overrides or {})}
        status, steps = "ok", []
        for step in recipe["steps"]:
            report = self.run_op(step.get("op") or step["check"], asset, _fill(step.get("params", {}), values))
            steps.append(report)
            asset = asset.partition("@")[0]  # only the first step reads a pinned version
            if report["status"] == "fail":
                if step.get("on_fail", "stop") == "stop":
                    status = "fail"
                    break
                status = "warn"
            elif report["status"] == "warn" and status == "ok":
                status = "warn"
        return {"recipe": name, "status": status, "steps": steps}
