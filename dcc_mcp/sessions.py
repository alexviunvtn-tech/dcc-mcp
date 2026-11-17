from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from .registry import Registry

# off -> starting -> ready <-> busy ; any -> lost (program died), next call restarts it


@dataclass
class Session:
    backend: Any
    mode: str
    info: dict = field(default_factory=dict)
    state: str = "starting"
    lock: threading.Lock = field(default_factory=threading.Lock)


class Sessions:
    def __init__(self, registry: Registry, on_event: Callable[[str, str, dict], None]) -> None:
        self._registry = registry
        self._on_event = on_event
        self._all: dict[str, Session] = {}

    def start(self, name: str, mode: str | None = None) -> Session:
        if name not in self._registry.backends:
            raise KeyError(f"unknown backend {name!r}")
        old = self._all.get(name)
        backend = self._registry.backends[name]()  # constructing launches nothing
        mode = mode or backend.default_mode
        if old and old.state in ("ready", "busy") and old.mode == mode:
            return old
        if old and old.state == "busy":
            raise RuntimeError(f"{name} is busy; try again when the current call ends")
        if old:
            self.stop(name)
        session = Session(backend=backend, mode=mode)
        self._all[name] = session
        try:
            session.info = backend.start(mode)
        except Exception:
            session.state = "off"
            raise
        backend.subscribe(lambda event, data: self._event(name, event, data))
        session.state = "ready"
        return session

    def ensure(self, name: str) -> Session:
        session = self._all.get(name)
        if session and session.state == "ready" and not session.backend.health():
            session.state = "lost"
        if session is None or session.state in ("off", "lost"):
            return self.start(name, session.mode if session else None)
        return session

    def _event(self, name: str, event: str, data: dict) -> None:
        if event == "lost" and name in self._all:
            self._all[name].state = "lost"
        self._on_event(name, event, data)

    def stop(self, name: str) -> None:
        session = self._all.pop(name, None)
        if session:
            try:
                session.backend.stop()
            except Exception:
                pass  # the program may already be gone

    def stop_all(self) -> None:
        for name in list(self._all):
            self.stop(name)

    def status(self) -> dict:
        return {n: {"state": s.state, "mode": s.mode, **s.info} for n, s in self._all.items()}
