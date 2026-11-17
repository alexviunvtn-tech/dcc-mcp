from __future__ import annotations

from pathlib import Path
from typing import Callable

import yaml
from jsonschema import Draft202012Validator

from .contract import CONTRACT_VERSION, Backend, OpSpec


class RegistryError(ValueError):
    pass


class Registry:
    def __init__(self) -> None:
        self.backends: dict[str, Callable[[], Backend]] = {}
        self.ops: dict[str, OpSpec] = {}
        self.recipes: dict[str, dict] = {}

    def add_backend(self, name: str, factory: Callable[[], Backend]) -> None:
        if name in self.backends:
            raise RegistryError(f"backend {name!r} is already registered")
        self.backends[name] = factory

    def add_op(self, spec: OpSpec) -> None:
        if spec.key in self.ops:
            raise RegistryError(f"operation {spec.key!r} is already registered")
        backend, _, action = spec.key.partition(".")
        if backend != spec.backend or not action:
            raise RegistryError(f"key {spec.key!r} must look like '{spec.backend}.<action>'")
        if spec.backend not in self.backends:
            raise RegistryError(f"{spec.key!r}: backend {spec.backend!r} is not registered")
        if spec.kind not in ("op", "check"):
            raise RegistryError(f"{spec.key!r}: kind must be 'op' or 'check'")
        Draft202012Validator.check_schema(spec.params_schema)
        self.ops[spec.key] = spec

    def load_recipes(self, folder: Path) -> None:
        for path in sorted(folder.glob("*.yaml")):
            self.add_recipe(path.stem, yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    def add_recipe(self, name: str, recipe: dict) -> None:
        if recipe.get("contract") != CONTRACT_VERSION:
            raise RegistryError(f"recipe {name!r}: needs 'contract: {CONTRACT_VERSION}'")
        steps = recipe.get("steps") or []
        if not steps:
            raise RegistryError(f"recipe {name!r}: has no steps")
        for i, step in enumerate(steps, 1):
            key = step.get("op") or step.get("check")
            if key not in self.ops:
                raise RegistryError(f"recipe {name!r}: step {i} uses unknown operation {key!r}")
            if step.get("on_fail", "stop") not in ("stop", "warn"):
                raise RegistryError(f"recipe {name!r}: step {i} on_fail must be 'stop' or 'warn'")
        self.recipes[name] = recipe
