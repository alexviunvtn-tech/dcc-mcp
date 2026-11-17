"""Commands the DCC-MCP backend sends into Krita. Runs inside Krita on the Qt main thread.

No Qt imports here: the krita module is passed in, so tests can use a stand-in.
"""
from __future__ import annotations

import contextlib
import hmac
import io
import json
import os
import sys
import traceback
from pathlib import Path


class BridgeError(Exception):
    """Expected failure with a message for the model (unknown layer, closed document...)."""


def state_file() -> Path:
    """Where the bridge publishes {port, token, pid}; the backend has the same rule."""
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "krita" / "dccmcp_bridge.json"
    return Path.home() / ".local" / "share" / "krita" / "dccmcp_bridge.json"


def respond(bridge: "Bridge", token: str, line: bytes) -> dict:
    """One request line -> one response dict. Never raises."""
    try:
        req = json.loads(line)
        rid = req.get("id")
    except (ValueError, AttributeError):
        return {"id": None, "ok": False, "error": "request is not a JSON object"}
    # trust boundary: krita.python runs any code, so only the backend that read our token gets in
    if not hmac.compare_digest(str(req.get("token", "")), token):
        return {"id": rid, "ok": False, "error": "bad token"}
    try:
        return {"id": rid, "ok": True, "result": bridge.handle(req.get("cmd", ""), req.get("args") or {})}
    except BridgeError as e:
        return {"id": rid, "ok": False, "error": str(e)}
    except Exception as e:  # a Krita or script error must not kill the bridge
        return {"id": rid, "ok": False, "error": f"{type(e).__name__}: {e}",
                "trace": traceback.format_exc(limit=5)}


def _plain(value):
    """JSON-safe copy; anything Qt/Krita becomes its repr."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        if isinstance(value, dict):
            return {str(k): _plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [_plain(v) for v in value]
        return repr(value)


def _rect(r) -> list[int] | None:
    return None if r is None else [r.x(), r.y(), r.width(), r.height()]


class Bridge:
    COMMANDS = ("ping", "open", "new", "info", "layer", "filter", "action", "catalog", "save", "python")

    def __init__(self, krita_module) -> None:
        self.k = krita_module
        self.doc = None  # working document: the last one opened or created through the bridge

    @property
    def app(self):
        return self.k.Krita.instance()

    def handle(self, cmd: str, args: dict):
        if cmd not in self.COMMANDS:
            raise BridgeError(f"unknown command {cmd!r}")
        return getattr(self, "cmd_" + cmd)(**args)

    # --- helpers ---
    def _working(self):
        # a closed document's wrapper loses its KisDocument and returns no root node
        if self.doc is None or self.doc.rootNode() is None:
            raise BridgeError("no working document: run krita.open (or krita.new) first")
        return self.doc

    def _show(self, doc) -> None:
        window = self.app.activeWindow()
        if window is None:
            raise BridgeError("Krita has no main window yet; try again in a moment")
        window.addView(doc)
        self.doc = doc

    def _node(self, doc, name: str | None):
        if not name:
            node = doc.activeNode()
            if node is None:
                raise BridgeError("no active layer; pass target")
            return node
        node = doc.nodeByName(name)
        if node is None:
            raise BridgeError(f"no layer named {name!r}; see krita.info")
        return node

    def _whole(self, doc):
        sel = self.k.Selection()
        sel.select(0, 0, doc.width(), doc.height(), 255)
        return sel

    def _filter(self, name: str, config: dict | None):
        if name not in self.app.filters():
            raise BridgeError(f"unknown filter {name!r}; see krita.catalog kind=filters")
        f = self.app.filter(name)
        cfg = f.configuration()
        for key, value in (config or {}).items():
            cfg.setProperty(key, value)
        f.setConfiguration(cfg)
        return f

    def _tree(self, node) -> dict:
        return {"name": node.name(), "id": node.uniqueId().toString().strip("{}"), "type": node.type(),
                "visible": node.visible(), "opacity": round(node.opacity() / 255, 3),
                "blend": node.blendingMode(), "locked": node.locked(), "alpha_locked": node.alphaLocked(),
                "bounds": _rect(node.bounds()),
                "children": [self._tree(c) for c in reversed(node.childNodes())]}  # top layer first

    def _done(self, doc) -> None:
        doc.waitForDone()
        doc.refreshProjection()

    # --- commands ---
    def cmd_ping(self):
        return {"krita": self.app.version(), "window": self.app.activeWindow() is not None}

    def cmd_open(self, path: str):
        doc = self.app.openDocument(path)
        if doc is None:
            raise BridgeError(f"Krita could not open {path}")
        self._show(doc)
        return self.cmd_info()

    def cmd_new(self, width: int, height: int, name: str = "untitled", color_model: str = "RGBA",
                color_depth: str = "U8", profile: str = "", resolution: float = 300.0):
        # empty profile -> Krita's default profile for that model and depth
        doc = self.app.createDocument(width, height, name, color_model, color_depth, profile, resolution)
        if doc is None:
            raise BridgeError(f"Krita refused {color_model}/{color_depth}/{profile!r}; see krita.catalog")
        self._show(doc)
        return self.cmd_info()

    def cmd_info(self):
        doc = self._working()
        active = doc.activeNode()
        return {"name": doc.name(), "file": doc.fileName(), "width": doc.width(), "height": doc.height(),
                "resolution": doc.resolution(), "color_model": doc.colorModel(),
                "color_depth": doc.colorDepth(), "profile": doc.colorProfile(), "modified": doc.modified(),
                "active_layer": active.name() if active else None,
                "selection": _rect(doc.selection()),
                "layers": self._tree(doc.rootNode())["children"]}

    def cmd_layer(self, action: str, target: str | None = None, name: str | None = None,
                  type: str = "paint", parent: str | None = None, above: str | None = None,
                  filter: str | None = None, generator: str | None = None, config: dict | None = None,
                  opacity: float | None = None, blend: str | None = None, visible: bool | None = None,
                  locked: bool | None = None, alpha_locked: bool | None = None):
        doc = self._working()
        if action == "add":
            name = name or f"{type} layer"
            if type == "paint":
                node = doc.createNode(name, "paintlayer")
            elif type == "group":
                node = doc.createNode(name, "grouplayer")
            elif type == "vector":
                node = doc.createVectorLayer(name)
            elif type == "filter":
                node = doc.createFilterLayer(name, self._filter(filter or "", config), self._whole(doc))
            elif type == "fill":
                info = self.k.InfoObject()
                for key, value in (config or {}).items():
                    info.setProperty(key, value)
                node = doc.createFillLayer(name, generator or "color", info, self._whole(doc))
            else:
                raise BridgeError(f"unknown layer type {type!r}")
            dest = self._node(doc, parent) if parent else doc.rootNode()
            dest.addChildNode(node, self._node(doc, above) if above else None)
            doc.setActiveNode(node)
        else:
            node = self._node(doc, target)
            if action == "delete":
                node.remove()
            elif action == "rename":
                if not name:
                    raise BridgeError("rename needs name")
                node.setName(name)
            elif action == "move":
                dest = self._node(doc, parent) if parent else doc.rootNode()
                anchor = self._node(doc, above) if above else None  # None = top of dest
                node.remove()
                dest.addChildNode(node, anchor)
            elif action == "duplicate":
                copy = node.duplicate()
                copy.setName(name or f"{node.name()} copy")
                node.parentNode().addChildNode(copy, node)
                node = copy
            elif action == "merge_down":
                node = node.mergeDown()
            elif action == "set":
                if opacity is not None:
                    node.setOpacity(round(opacity * 255))
                if blend is not None:
                    node.setBlendingMode(blend)
                if visible is not None:
                    node.setVisible(visible)
                if locked is not None:
                    node.setLocked(locked)
                if alpha_locked is not None:
                    node.setAlphaLocked(alpha_locked)
            elif action == "activate":
                doc.setActiveNode(node)
            else:
                raise BridgeError(f"unknown layer action {action!r}")
        self._done(doc)
        return {"layer": node.name() if node is not None and action != "delete" else None,
                "layers": self._tree(doc.rootNode())["children"]}

    def cmd_filter(self, name: str, config: dict | None = None, target: str | None = None,
                   selection_only: bool = True):
        doc = self._working()
        node = self._node(doc, target)
        f = self._filter(name, config)
        sel = doc.selection() if selection_only else None
        x, y, w, h = _rect(sel) if sel is not None else (0, 0, doc.width(), doc.height())
        f.apply(node, x, y, w, h)
        self._done(doc)
        return {"filter": name, "layer": node.name(), "area": [x, y, w, h],
                "config": _plain(f.configuration().properties())}

    def cmd_action(self, name: str):
        action = self.app.action(name)
        if action is None:
            raise BridgeError(f"unknown action {name!r}; see krita.catalog kind=actions")
        action.trigger()
        if self.doc is not None and self.doc.rootNode() is not None:
            self._done(self.doc)
        return {"action": name, "text": action.text().replace("&", ""),
                "checked": action.isChecked() if action.isCheckable() else None}

    def cmd_catalog(self, kind: str, contains: str = "", model: str = "RGBA", depth: str = "U8",
                    limit: int = 200):
        app = self.app
        if kind == "actions":
            items = [{"name": a.objectName(), "text": a.text().replace("&", "")}
                     for a in app.actions() if a.objectName()]
        elif kind == "filters":
            items = list(app.filters())
        elif kind == "brush_presets":
            items = list(app.resources("preset").keys())
        elif kind == "color_models":
            items = [{"model": m, "depths": list(app.colorDepths(m))} for m in app.colorModels()]
        elif kind == "profiles":
            items = list(app.profiles(model, depth))
        else:
            raise BridgeError(f"unknown catalog kind {kind!r}")
        needle = contains.lower()
        if needle:
            items = [i for i in items if needle in json.dumps(i, ensure_ascii=False).lower()]
        return {"kind": kind, "total": len(items), "items": items[:limit]}

    def cmd_save(self, path: str, format: str):
        doc = self._working()
        doc.setBatchmode(True)  # no export-options dialogs
        try:
            # saveAs moves the document onto the new file; export leaves it on its .kra
            ok = doc.saveAs(path) if format == "kra" else doc.exportImage(path, self.k.InfoObject())
            doc.waitForDone()
        finally:
            doc.setBatchmode(False)
        if not ok or not Path(path).exists():
            raise BridgeError(f"Krita did not write {path}")
        return {"file": path}

    def cmd_python(self, code: str):
        ns = {"krita": self.k, "Krita": self.k.Krita, "app": self.app, "doc": self.doc, "result": None}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            exec(compile(code, "<krita.python>", "exec"), ns)
        if ns.get("doc") is not None and ns["doc"] is not self.doc:
            self.doc = ns["doc"]  # a script may switch the working document by assigning doc
        return {"result": _plain(ns.get("result")), "stdout": out.getvalue()[-20000:]}
