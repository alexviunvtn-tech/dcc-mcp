"""krita plugin without Krita: bridge commands against a stand-in krita module,
the backend against a real socket server running the bridge's respond()."""
import json
import socket
import threading
import types
from pathlib import Path

import pytest

from dcc_mcp.app import build_core
from dcc_mcp.registry import Registry
from plugins.krita import register
from plugins.krita.backend import KritaBackend, KritaError
from plugins.krita.bridge.dccmcp_bridge.commands import Bridge, respond
from plugins.krita.install import enable_in_kritarc, install

ROOT = Path(__file__).resolve().parent.parent


# ---------- stand-in krita module ----------
class Rect:
    def __init__(self, x, y, w, h):
        self.v = (x, y, w, h)

    def x(self): return self.v[0]
    def y(self): return self.v[1]
    def width(self): return self.v[2]
    def height(self): return self.v[3]


class Node:
    def __init__(self, name, type="paintlayer"):
        self._name, self._type, self.parent, self.children = name, type, None, []
        self._opacity, self._blend, self._visible, self._locked, self._alpha = 255, "normal", True, False, False

    def name(self): return self._name
    def setName(self, n): self._name = n
    def type(self): return self._type
    def uniqueId(self): return types.SimpleNamespace(toString=lambda: "{id-%s}" % self._name)
    def visible(self): return self._visible
    def setVisible(self, v): self._visible = v
    def opacity(self): return self._opacity
    def setOpacity(self, v): self._opacity = v
    def blendingMode(self): return self._blend
    def setBlendingMode(self, b): self._blend = b
    def locked(self): return self._locked
    def setLocked(self, v): self._locked = v
    def alphaLocked(self): return self._alpha
    def setAlphaLocked(self, v): self._alpha = v
    def bounds(self): return Rect(0, 0, 10, 10)
    def childNodes(self): return list(self.children)
    def parentNode(self): return self.parent

    def addChildNode(self, child, above):
        child.parent = self
        # Krita: no 'above' puts the child on top of the stack (end of childNodes)
        self.children.insert(self.children.index(above) + 1 if above else len(self.children), child)

    def remove(self):
        self.parent.children.remove(self)
        self.parent = None


class Doc:
    def __init__(self, path="", w=64, h=32):
        self.path, self.w, self.h, self.closed, self.batch = path, w, h, False, []
        self.root = Node("root", "grouplayer")
        self.active = None
        self.root.addChildNode(Node("Background"), None)
        self.active = self.root.children[0]

    def rootNode(self): return None if self.closed else self.root
    def name(self): return Path(self.path).stem
    def fileName(self): return self.path
    def width(self): return self.w
    def height(self): return self.h
    def resolution(self): return 300
    def colorModel(self): return "RGBA"
    def colorDepth(self): return "U8"
    def colorProfile(self): return "sRGB-elle-V2-srgbtrc.icc"
    def modified(self): return False
    def selection(self): return None
    def activeNode(self): return self.active
    def setActiveNode(self, n): self.active = n
    def waitForDone(self): pass
    def refreshProjection(self): pass
    def setBatchmode(self, v): self.batch.append(v)

    def nodeByName(self, name):
        stack = list(self.root.children)
        while stack:
            n = stack.pop()
            if n.name() == name:
                return n
            stack += n.children

    def createNode(self, name, type): return Node(name, type)
    def createVectorLayer(self, name): return Node(name, "vectorlayer")

    def saveAs(self, path):
        Path(path).write_text("kra", encoding="utf-8")
        self.path = path
        return True

    def exportImage(self, path, info):
        Path(path).write_text("png", encoding="utf-8")
        return True


class Action:
    def __init__(self, name): self.name, self.fired = name, 0
    def objectName(self): return self.name
    def text(self): return "&Flatten Image" if self.name == "image_flatten" else "Select &All"
    def trigger(self): self.fired += 1
    def isCheckable(self): return False


class App:
    def __init__(self):
        self.docs, self.views = {}, []
        self.flatten = Action("image_flatten")

    def version(self): return "5.3.2.1"
    def activeWindow(self): return types.SimpleNamespace(addView=self.views.append)

    def openDocument(self, path):
        return self.docs.setdefault(path, Doc(path)) if Path(path).exists() else None

    def createDocument(self, w, h, name, model, depth, profile, res): return Doc(f"{name}.kra", w, h)
    def action(self, name): return self.flatten if name == "image_flatten" else None
    def actions(self): return [self.flatten, Action("select_all")]
    def filters(self): return ["blur", "levels"]
    def filter(self, name): return Filter()


class Info:
    def __init__(self): self.props = {"halfWidth": 5}
    def setProperty(self, k, v): self.props[k] = v
    def properties(self): return dict(self.props)


class Filter:
    applied = []

    def __init__(self): self.cfg = Info()
    def configuration(self): return self.cfg
    def setConfiguration(self, c): self.cfg = c
    def apply(self, node, x, y, w, h): Filter.applied.append((node.name(), x, y, w, h, self.cfg.props["halfWidth"]))


@pytest.fixture
def k():
    app = App()
    return types.SimpleNamespace(Krita=types.SimpleNamespace(instance=lambda: app), InfoObject=object, app=app)


@pytest.fixture
def opened(k, tmp_path):
    src = tmp_path / "v001_art.kra"
    src.write_text("kra", encoding="utf-8")
    bridge = Bridge(k)
    bridge.handle("open", {"path": str(src)})
    return bridge, tmp_path


# ---------- bridge ----------
def test_respond_checks_token_json_and_command(k):
    b = Bridge(k)
    assert respond(b, "t", b'{"id": 1, "token": "x", "cmd": "ping"}')["error"] == "bad token"
    assert respond(b, "t", b"not json")["ok"] is False
    assert "unknown command" in respond(b, "t", b'{"id": 2, "token": "t", "cmd": "rm"}')["error"]
    ok = respond(b, "t", b'{"id": 3, "token": "t", "cmd": "ping"}')
    assert ok == {"id": 3, "ok": True, "result": {"krita": "5.3.2.1", "window": True}}


def test_commands_need_an_open_document_and_notice_when_it_is_closed(opened, k):
    assert "krita.open" in respond(Bridge(k), "t", b'{"token": "t", "cmd": "info"}')["error"]
    bridge, _ = opened
    bridge.doc.closed = True
    assert "no working document" in respond(bridge, "t", b'{"token": "t", "cmd": "info"}')["error"]


def test_open_shows_document_and_info_lists_layers(opened, k):
    bridge, _ = opened
    assert k.app.views == [bridge.doc]
    info = bridge.handle("info", {})
    assert info["width"] == 64 and info["active_layer"] == "Background"
    assert [l["name"] for l in info["layers"]] == ["Background"]
    assert info["layers"][0]["id"] == "id-Background"  # QUuid as plain text, no braces


def test_layer_add_set_move_rename_delete(opened):
    bridge, _ = opened
    bridge.handle("layer", {"action": "add", "name": "Ink"})
    bridge.handle("layer", {"action": "add", "type": "group", "name": "Group"})
    r = bridge.handle("layer", {"action": "set", "target": "Ink", "opacity": 0.5, "blend": "multiply",
                                "visible": False})
    ink = next(l for l in r["layers"] if l["name"] == "Ink")
    assert ink["opacity"] == 0.502 and ink["blend"] == "multiply" and ink["visible"] is False
    r = bridge.handle("layer", {"action": "move", "target": "Ink", "parent": "Group"})
    assert [l["name"] for l in r["layers"]] == ["Group", "Background"]
    assert r["layers"][0]["children"][0]["name"] == "Ink"
    bridge.handle("layer", {"action": "rename", "target": "Ink", "name": "Lines"})
    r = bridge.handle("layer", {"action": "delete", "target": "Group"})
    assert [l["name"] for l in r["layers"]] == ["Background"]
    with pytest.raises(Exception, match="no layer named 'Ink'"):
        bridge.handle("layer", {"action": "set", "target": "Ink", "opacity": 1})


def test_save_kra_moves_document_export_does_not(opened):
    bridge, tmp = opened
    bridge.handle("save", {"path": str(tmp / "v002_krita.kra"), "format": "kra"})
    assert bridge.doc.fileName().endswith("v002_krita.kra")
    bridge.handle("save", {"path": str(tmp / "v003_krita.png"), "format": "png"})
    assert bridge.doc.fileName().endswith("v002_krita.kra") and (tmp / "v003_krita.png").exists()
    assert bridge.doc.batch == [True, False, True, False]


def test_action_catalog_and_python(opened, k):
    bridge, _ = opened
    assert bridge.handle("action", {"name": "image_flatten"})["text"] == "Flatten Image"
    assert k.app.flatten.fired == 1
    assert "unknown action" in respond(bridge, "t", b'{"token":"t","cmd":"action","args":{"name":"x"}}')["error"]
    cat = bridge.handle("catalog", {"kind": "actions", "contains": "flatten"})
    assert cat["items"] == [{"name": "image_flatten", "text": "Flatten Image"}]
    r = bridge.handle("python", {"code": "print(doc.width())\nresult = {'n': len(app.filters())}"})
    assert r == {"result": {"n": 2}, "stdout": "64\n"}
    r = respond(bridge, "t", json.dumps({"token": "t", "cmd": "python", "args": {"code": "1/0"}}).encode())
    assert r["ok"] is False and "ZeroDivisionError" in r["error"]


def test_filter_applies_config_to_layer_or_whole_image(opened):
    bridge, _ = opened
    r = bridge.handle("filter", {"name": "blur", "config": {"halfWidth": 9}})
    assert r["config"] == {"halfWidth": 9} and Filter.applied[-1] == ("Background", 0, 0, 64, 32, 9)
    assert "unknown filter" in respond(bridge, "t", b'{"token":"t","cmd":"filter","args":{"name":"x"}}')["error"]


# ---------- backend over a real socket ----------
class FakeKrita:
    """Socket server speaking the bridge protocol, backed by a stand-in Bridge."""

    def __init__(self, k, state_path, token="tok"):
        self.bridge, self.token = Bridge(k), token
        self.srv = socket.create_server(("127.0.0.1", 0))
        self.state_path = state_path
        self.conns = []
        threading.Thread(target=self._serve, daemon=True).start()

    def publish(self):
        self.state_path.write_text(json.dumps({"port": self.srv.getsockname()[1], "token": self.token}))

    def _serve(self):
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            self.conns.append(conn)
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn):
        try:
            for line in conn.makefile("rb"):
                conn.sendall(json.dumps(respond(self.bridge, self.token, line)).encode() + b"\n")
        except OSError:  # die() resets the connection under us
            return

    def die(self):
        self.srv.close()
        for c in self.conns:
            c.shutdown(socket.SHUT_RDWR)
            c.close()


def test_backend_connects_to_running_krita_and_reports_errors(k, tmp_path):
    fake = FakeKrita(k, tmp_path / "state.json")
    fake.publish()
    b = KritaBackend({"state_file": str(tmp_path / "state.json")}, launch=lambda argv: pytest.fail("launched"))
    assert b.start("live")["version"] == "5.3.2.1"
    with pytest.raises(KritaError, match="krita.open"):
        b.call("info")
    events = []
    b.subscribe(lambda e, d: events.append(e))
    fake.die()
    assert b.health() is False and events == ["lost"]


def test_backend_launches_krita_when_no_bridge_answers(k, tmp_path):
    exe = tmp_path / "krita.exe"
    exe.write_text("")
    fake = FakeKrita(k, tmp_path / "state.json")
    launched = []
    b = KritaBackend({"state_file": str(tmp_path / "state.json"), "exe": str(exe), "start_timeout": 5},
                     launch=lambda argv: (launched.append(argv), fake.publish()))
    b.start("live")
    assert launched == [[str(exe), "--nosplash"]]


def test_backend_refuses_headless_wrong_token_and_missing_exe(k, tmp_path):
    with pytest.raises(ValueError, match="live"):
        KritaBackend({}).start("headless")
    fake = FakeKrita(k, tmp_path / "state.json", token="other")
    fake.state_path.write_text(json.dumps({"port": fake.srv.getsockname()[1], "token": "stale"}))
    b = KritaBackend({"state_file": str(fake.state_path), "exe": str(tmp_path / "nope.exe")})
    with pytest.raises(KritaError, match="not found"):
        b.start("live")


# ---------- through the core ----------
@pytest.fixture
def core(k, tmp_path, monkeypatch):
    fake = FakeKrita(k, tmp_path / "state.json")
    fake.publish()
    cfg = tmp_path / "dcc_mcp.toml"
    cfg.write_text(f"plugins = ['krita']\nplugin_paths = ['{ROOT.as_posix()}']\nwork_dir = 'work'\n"
                   f"recipes_dir = '{(ROOT / 'recipes').as_posix()}'\n"
                   f"[krita]\nstate_file = '{(tmp_path / 'state.json').as_posix()}'\nallow_raw = true\n",
                   encoding="utf-8")
    monkeypatch.setattr("dcc_mcp.registry.Registry.load_recipes",
                        lambda self, folder: self.add_recipe("krita_export", __import__("yaml").safe_load(
                            (ROOT / "plugins" / "krita" / "examples" / "krita_export.yaml").read_text(encoding="utf-8"))))
    c = build_core(cfg)
    src = tmp_path / "art.kra"
    src.write_text("kra", encoding="utf-8")
    c.assets.import_file("art", src)
    return c


def test_recipe_opens_and_saves_two_versions(core):
    r = core.runner.run_recipe("krita_export", "art")
    assert r["status"] == "ok", r
    assert core.assets.info("art")["versions"] == ["v001_art.kra", "v002_krita.kra", "v003_krita.png"]


def test_new_canvas_saved_into_blank_asset(core):
    core.assets.import_file("poster", ROOT / "plugins" / "krita" / "blank.png")
    assert core.runner.run_op("krita.new", None, {"width": 2048, "height": 1024})["metrics"]["width"] == 2048
    assert core.runner.run_op("krita.save", "poster", {"format": "png"})["status"] == "ok"
    assert core.assets.info("poster")["versions"][-1] == "v002_krita.png"


def test_raw_python_only_when_allowed():
    reg = Registry()
    register(reg, {})
    assert "krita.python" not in reg.ops and "krita.action" in reg.ops


# ---------- installer ----------
def test_kritarc_edit_keeps_other_lines(tmp_path):
    assert enable_in_kritarc("") == "[python]\nenable_dccmcp_bridge=true\n"
    rc = "[General]\nx=1\n[python]\nenable_foo=true\nenable_dccmcp_bridge=false\n[Zeta]\ny=2\n"
    assert enable_in_kritarc(rc) == rc.replace("bridge=false", "bridge=true")
    rc = "[General]\nx=1\n[python]\nenable_foo=true\n"
    assert enable_in_kritarc(rc) == "[General]\nx=1\n[python]\nenable_dccmcp_bridge=true\nenable_foo=true\n"
    install(tmp_path / "pykrita", tmp_path / "kritarc")
    assert (tmp_path / "pykrita" / "dccmcp_bridge" / "commands.py").exists()
    assert (tmp_path / "pykrita" / "dccmcp_bridge.desktop").exists()
