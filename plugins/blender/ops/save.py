from dcc_mcp.contract import Ctx, OpResult, OpSpec


def run(ctx: Ctx, params: dict) -> OpResult:
    out = ctx.new_version_path("blend")
    ctx.session.call("save", ctx.input_path, out)
    return OpResult(files=[str(out)])


SPEC = OpSpec(
    key="blender.save", backend="blender", run=run, needs=frozenset({"bpy"}),
    summary="Save the asset's current version as a .blend: the next version (imports a mesh file first).",
    params_schema={"type": "object", "additionalProperties": False},
)
