import asyncio

import pytest

from dcc_mcp.assets import AssetError
from dcc_mcp.contract import OpResult, OpSpec
from dcc_mcp.registry import RegistryError


def test_op_writes_new_version_and_history(core):
    r = core.runner.run_op("fake.touch", "chair", {"n": 2})
    assert r["status"] == "ok" and r["metrics"] == {"n": 2}
    info = core.assets.info("chair")
    assert info["versions"] == ["v001_chair.obj", "v002_fake.obj"]
    assert info["history"][0]["input"] == "v001_chair.obj"
    assert info["history"][0]["output"] == ["v002_fake.obj"]


def test_pinned_version_is_read(core):
    core.runner.run_op("fake.touch", "chair")
    core.runner.run_op("fake.touch", "chair@v001")
    assert core.assets.info("chair")["history"][1]["input"] == "v001_chair.obj"
    assert core.runner.run_op("fake.touch", "chair@v009")["status"] == "fail"


def test_bad_params_unknown_key_missing_capability_and_errors_fail_cleanly(core):
    assert "bad params" in core.runner.run_op("fake.touch", "chair", {"n": "x"})["notes"]
    assert "unknown operation" in core.runner.run_op("fake.nope")["notes"]
    core.runner.sessions.start("fake", "headless")
    assert "lacks ['ui.viewport']" in core.runner.run_op("fake.view", None, {"result": "ok"})["notes"]
    r = core.runner.run_op("fake.boom", "chair")
    assert r["status"] == "fail" and "program said no" in r["notes"]


def test_program_that_fails_to_start_returns_a_report(core, monkeypatch):
    class ZEx(Exception):
        pass

    def refuse(self, mode):
        raise ZEx("exited with code 7")

    monkeypatch.setattr(core.registry.backends["fake"], "start", refuse)
    r = core.runner.run_recipe("two_checks", "chair")
    assert r["status"] == "fail" and r["steps"][0]["notes"] == "ZEx: exited with code 7"


def test_lost_session_restarts_in_same_mode(core):
    s = core.runner.sessions.start("fake", "headless")
    s.backend.alive = False
    before = len(s.backend.started)
    assert core.runner.run_op("fake.check", None, {"result": "ok"})["status"] == "ok"
    assert s.backend.started[before:] == ["headless"]


def test_recipe_warn_continues_stop_halts_and_params_keep_type(core):
    r = core.runner.run_recipe("two_checks", "chair")
    assert r["status"] == "fail"
    assert [s["status"] for s in r["steps"]] == ["ok", "warn", "fail"]
    assert r["steps"][0]["metrics"] == {"n": 3}  # "{n}" -> int 3, passed the integer schema
    r = core.runner.run_recipe("two_checks", "chair", {"hard": "ok"})
    assert r["status"] == "warn" and len(r["steps"]) == 4


def test_manual_edit_event_flags_asset(core):
    core.runner.run_op("fake.touch", "chair")  # the backend now holds chair
    core.runner.run_op("fake.edit_by_hand", "chair")
    r = core.runner.run_op("fake.check", "chair", {"result": "ok"})
    assert "edited by hand" in r["warning"]
    core.runner.run_op("fake.touch", "chair")  # a new saved version clears it
    assert core.assets.info("chair")["manual_edit"] is False


def test_registry_rejects_bad_definitions(core):
    reg = core.registry
    run = lambda ctx, p: OpResult()
    with pytest.raises(RegistryError, match="already registered"):
        reg.add_op(OpSpec(key="fake.touch", backend="fake", summary="", run=run))
    with pytest.raises(RegistryError, match="must look like"):
        reg.add_op(OpSpec(key="other.x", backend="fake", summary="", run=run))
    with pytest.raises(RegistryError, match="unknown operation"):
        reg.add_recipe("bad", {"contract": 1, "steps": [{"op": "fake.missing"}]})
    with pytest.raises(RegistryError, match="contract"):
        reg.add_recipe("old", {"contract": 0, "steps": [{"op": "fake.touch"}]})


def test_asset_names_stay_inside_work_dir(core, tmp_path):
    with pytest.raises(AssetError):
        core.assets.import_file("../evil", tmp_path / "chair.obj")
    with pytest.raises(AssetError):
        core.runner.assets.resolve("..")


def test_work_dir_from_env(tmp_path, monkeypatch):
    from dcc_mcp.app import build_core
    from tests.conftest import FIXTURE

    cfg = tmp_path / "dcc_mcp.toml"
    cfg.write_text(f"plugins = ['fake']\nplugin_paths = ['{FIXTURE.as_posix()}']\n"
                   f"recipes_dir = '{(FIXTURE / 'recipes').as_posix()}'\n", encoding="utf-8")
    monkeypatch.setenv("DCC_MCP_WORK_DIR", str(tmp_path / "elsewhere"))
    assert build_core(cfg).assets.root == tmp_path / "elsewhere"


def test_server_exposes_fixed_tools_plus_featured(core):
    from dcc_mcp.server import build_server

    names = {t.name for t in asyncio.run(build_server(core).list_tools())}
    assert {"list_operations", "run_operation", "run_recipe", "import_asset", "stop_session",
            "fake_touch"} <= names
    assert "fake_boom" not in names


def test_stop_session_closes_program_and_refuses_when_busy(core):
    from dcc_mcp.server import build_server

    server = build_server(core)
    stop = lambda b: asyncio.run(server.call_tool("stop_session", {"backend": b}))
    assert "not running" in str(stop("fake"))
    session = core.runner.sessions.start("fake", "live")
    session.state = "busy"
    assert "busy" in str(stop("fake"))
    session.state = "ready"
    stop("fake")
    assert core.runner.sessions.status() == {} and session.backend.alive is False
