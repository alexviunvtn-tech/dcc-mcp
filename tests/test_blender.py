"""blender plugin without Blender: the backend against a fake `blender -b`, runner.py against a fake bpy."""
import importlib
import json
import sys
import types
from pathlib import Path

import pytest
import yaml

from dcc_mcp.assets import AssetStore
from dcc_mcp.registry import Registry
from dcc_mcp.runner import Runner
from plugins.blender import register
from plugins.blender.backend import RUNNER, BlenderBackend, BlenderError

ROOT = Path(__file__).resolve().parent.parent


class FakeBlender:
    """Stands in for subprocess.run(blender -b ...): reads the request, writes a result like runner.py."""

    def __init__(self, triangles=1200, fail=None, crash=False):
        self.triangles, self.fail, self.crash, self.calls = triangles, fail, crash, []

    def __call__(self, argv, **kw):
        req = json.loads(Path(argv[-2]).read_text(encoding="utf-8"))
        self.calls.append((argv, req))
        if self.crash:
            return types.SimpleNamespace(returncode=11, stdout="", stderr="EXCEPTION_ACCESS_VIOLATION\n")
        if self.fail == req["cmd"]:
            reply = {"ok": False, "error": "RuntimeError: Error: Cannot read file"}
        else:
            if req["output"]:
                Path(req["output"]).write_text(req["cmd"], encoding="utf-8")
            result = {"ping": {"version": "5.2.0"}, "info": {"objects": 1, "triangles": self.triangles}}
            reply = {"ok": True, "result": result.get(req["cmd"], {"file": req["output"]})}
        Path(argv[-1]).write_text(json.dumps(reply), encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")


def backend(tmp_path, fake):
    exe = tmp_path / "blender.exe"
    exe.write_text("")
    return BlenderBackend({"exe": str(exe)}, run=fake)


# ---------- backend ----------
def test_start_runs_background_blender_with_the_runner(tmp_path):
    fake = FakeBlender()
    b = backend(tmp_path, fake)
    assert b.start("headless")["version"] == "5.2.0" and b.health()
    argv, req = fake.calls[0]
    assert argv[1:5] == ["-b", "--factory-startup", "--python", str(RUNNER)] and argv[5] == "--"
    assert req == {"cmd": "ping", "args": {}, "input": None, "output": None}


def test_errors_reach_the_model(tmp_path):
    with pytest.raises(ValueError, match="headless"):
        BlenderBackend({}).start("live")
    with pytest.raises(BlenderError, match="not found"):
        BlenderBackend({"exe": str(tmp_path / "nope.exe")}).start("headless")
    with pytest.raises(BlenderError, match="Cannot read file"):
        backend(tmp_path, FakeBlender(fail="info")).call("info", tmp_path / "x.fbx")
    with pytest.raises(BlenderError, match="code 11 .*ACCESS_VIOLATION"):
        backend(tmp_path, FakeBlender(crash=True)).call("ping")


# ---------- through the core ----------
@pytest.fixture
def runner(tmp_path):
    def make(fake):
        reg = Registry()
        register(reg, {})
        reg.backends["blender"] = lambda: backend(tmp_path, fake)
        reg.add_recipe("blender_preview", yaml.safe_load(
            (ROOT / "plugins/blender/examples/blender_preview.yaml").read_text(encoding="utf-8")))
        mesh = tmp_path / "chair.fbx"
        mesh.write_text("fbx", encoding="utf-8")
        assets = AssetStore(tmp_path / "work")
        assets.import_file("chair", mesh)
        return Runner(reg, assets)
    return make


def test_preview_recipe_writes_blend_glb_png_in_order(runner):
    fake = FakeBlender()
    r = runner(fake).run_recipe("blender_preview", "chair")
    assert r["status"] == "ok", r
    reqs = [req for _, req in fake.calls if req["cmd"] != "ping"]
    assert [q["cmd"] for q in reqs] == ["info", "save", "export", "render"]
    assert [Path(q["input"]).name for q in reqs] == ["v001_chair.fbx", "v001_chair.fbx",
                                                     "v002_blender.blend", "v003_blender.glb"]
    assert reqs[2]["args"] == {"format": "glb", "options": {}}
    assert reqs[3]["args"] == {"width": 1024, "height": 1024}  # "{size}" keeps its integer type


def test_polycount_over_limit_only_warns_in_recipe(runner):
    r = runner(FakeBlender(triangles=500000)).run_recipe("blender_preview", "chair")
    assert r["status"] == "warn" and "500000 triangles > 200000" in r["steps"][0]["notes"]
    assert r["steps"][-1]["status"] == "ok"


def test_raw_python_only_when_allowed():
    reg = Registry()
    register(reg, {})
    assert "blender.python" not in reg.ops and "blender.export" in reg.ops


# ---------- runner.py with a fake bpy ----------
@pytest.fixture
def run_mod(monkeypatch):
    calls = []

    def operator(path):
        def call(**kw):
            calls.append((path, kw))
            return {"FINISHED"}
        call.get_rna_type = lambda: None
        return call

    def ns(module, names):
        return types.SimpleNamespace(**{n: operator(f"{module}.{n}") for n in names})

    bpy = types.ModuleType("bpy")
    bpy.app = types.SimpleNamespace(version_string="5.2.0")
    bpy.ops = types.SimpleNamespace(
        wm=ns("wm", ["read_factory_settings", "open_mainfile", "save_as_mainfile", "obj_import", "usd_import",
                     "stl_import", "ply_import", "obj_export", "usd_export", "ply_export"]),  # no stl_export
        import_scene=ns("import_scene", ["fbx", "gltf"]), export_scene=ns("export_scene", ["fbx", "gltf"]))
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    monkeypatch.delitem(sys.modules, "plugins.blender.runner", raising=False)
    mod = importlib.import_module("plugins.blender.runner")
    mod.calls = calls
    return mod


def test_load_opens_blend_and_imports_mesh_files(run_mod):
    run_mod.load("C:/a/v002.blend")
    run_mod.load("C:/a/v001.FBX")
    assert run_mod.calls == [("wm.open_mainfile", {"filepath": "C:/a/v002.blend"}),
                             ("wm.read_factory_settings", {"use_empty": True}),
                             ("import_scene.fbx", {"filepath": "C:/a/v001.FBX"})]
    with pytest.raises(run_mod.Refused, match="cannot open .png"):
        run_mod.load("C:/a/v004.png")


def test_export_merges_defaults_and_reports_missing_operator(run_mod):
    run_mod.handle({"cmd": "export", "input": "C:/a/v1.blend", "output": "C:/a/v2.glb",
                    "args": {"format": "glb", "options": {"export_apply": True}}})
    assert run_mod.calls[-1] == ("export_scene.gltf", {"filepath": "C:/a/v2.glb", "export_format": "GLB",
                                                       "export_apply": True})
    with pytest.raises(run_mod.Refused, match="no operator bpy.ops.wm.stl_export"):
        run_mod.handle({"cmd": "export", "input": None, "output": "C:/a/v2.stl", "args": {"format": "stl"}})


def test_main_writes_error_result_instead_of_crashing(run_mod, tmp_path, monkeypatch):
    req, res = tmp_path / "req.json", tmp_path / "res.json"
    req.write_text(json.dumps({"cmd": "teleport", "input": None, "output": None}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["blender", "-b", "--python", "runner.py", "--", str(req), str(res)])
    run_mod.main()
    assert json.loads(res.read_text(encoding="utf-8")) == {"ok": False, "error": "unknown command 'teleport'"}
