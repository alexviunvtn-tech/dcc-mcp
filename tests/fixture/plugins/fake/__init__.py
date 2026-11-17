"""Test backend: no program behind it, records what it was asked to do."""
from dcc_mcp.contract import OpResult, OpSpec


class FakeBackend:
    name = "fake"
    default_mode = "live"
    started: list = []  # class-level so tests can see every instance's starts

    def __init__(self):
        self.mode = None
        self.alive = True
        self.handlers = []

    def start(self, mode):
        self.mode = mode
        FakeBackend.started.append(mode)
        return {"version": "1.0"}

    def stop(self):
        self.alive = False

    def health(self):
        return self.alive

    def capabilities(self):
        return {"uv", "ui.viewport"} if self.mode == "live" else {"uv"}

    def subscribe(self, handler):
        self.handlers.append(handler)


def _touch(ctx, params):
    path = ctx.new_version_path("obj")
    path.write_text(f"from {ctx.input_path.name}", encoding="utf-8")
    return OpResult(files=[str(path)], metrics={"n": params.get("n", 0)})


def _check(ctx, params):
    return OpResult(params["result"], metrics={"value": params.get("value")})


def _boom(ctx, params):
    raise RuntimeError("program said no")


def _edit_by_hand(ctx, params):
    for h in ctx.session.handlers:
        h("changed", {})
    return OpResult()


def register(registry, cfg):
    registry.add_backend("fake", FakeBackend)
    registry.add_op(OpSpec(key="fake.touch", backend="fake", summary="write a new version", run=_touch,
                           params_schema={"type": "object", "properties": {"n": {"type": "integer"}},
                                          "additionalProperties": False}, featured=True))
    registry.add_op(OpSpec(key="fake.check", backend="fake", summary="return a status", run=_check,
                           kind="check", params_schema={"type": "object", "required": ["result"]}))
    registry.add_op(OpSpec(key="fake.boom", backend="fake", summary="raise", run=_boom))
    registry.add_op(OpSpec(key="fake.view", backend="fake", summary="needs a window", run=_check,
                           needs=frozenset({"ui.viewport"})))
    registry.add_op(OpSpec(key="fake.edit_by_hand", backend="fake", summary="emit changed", run=_edit_by_hand))
