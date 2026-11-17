from dcc_mcp.contract import Ctx, OpResult, OpSpec


def run(ctx: Ctx, params: dict) -> OpResult:
    out = ctx.new_version_path("blend")
    m = ctx.session.call("python", ctx.input_path, out, {"code": params["code"]})
    return OpResult(metrics={"result": m["result"], "stdout": m["stdout"]}, files=[str(out)])


SPEC = OpSpec(
    key="blender.python", backend="blender", run=run, needs=frozenset({"bpy"}),
    summary=("Run a bpy script on the asset's current version in background Blender and save the scene as the "
             "next .blend version. Names ready: bpy. Set 'result' to return a value; print() output comes back "
             "too. Enabled by [blender] allow_raw."),
    params_schema={"type": "object", "required": ["code"], "additionalProperties": False,
                   "properties": {"code": {"type": "string"}}},
)
