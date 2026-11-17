"""Contract v1 between the core and plugins.

Change it only by adding optional fields, so plugins written for v1 keep working.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

CONTRACT_VERSION = 1

# (event, data); events: "changed" (data edited outside our calls), "lost" (program gone)
EventHandler = Callable[[str, dict], None]


class Backend(Protocol):
    """One running program (RizomUV, ZBrush...). Owned by the core's Sessions."""

    name: str
    default_mode: str

    def start(self, mode: str) -> dict: ...
    def stop(self) -> None: ...
    def health(self) -> bool: ...
    def capabilities(self) -> set[str]: ...
    def subscribe(self, handler: EventHandler) -> None: ...


@dataclass
class OpResult:
    status: str = "ok"  # ok | warn | fail
    metrics: dict[str, Any] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)  # new asset versions the op wrote
    notes: str = ""


@dataclass
class Ctx:
    session: Any  # the plugin's own backend object
    asset: str | None
    input_path: Path | None  # asset version the op should read
    new_version_path: Callable[[str], Path]  # extension -> where to write the next version
    log: Callable[[str], None]


@dataclass(frozen=True)
class OpSpec:
    """Definition of an operation (shared); a call with params is the instance."""

    key: str  # "<backend>.<action>"
    backend: str
    summary: str
    run: Callable[[Ctx, dict], OpResult]
    params_schema: dict = field(default_factory=lambda: {"type": "object"})
    kind: str = "op"  # op | check
    needs: frozenset[str] = frozenset()  # capability flags the backend must report
    featured: bool = False  # also exposed as its own MCP tool
