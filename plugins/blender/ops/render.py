from dcc_mcp.contract import Ctx, OpResult, OpSpec


def run(ctx: Ctx, params: dict) -> OpResult:
    out = ctx.new_version_path("png")
    m = ctx.session.call("render", ctx.input_path, out, params)
    return OpResult(metrics=m, files=[str(out)])


SPEC = OpSpec(
    key="blender.render", backend="blender", run=run, needs=frozenset({"bpy"}), featured=True,
    summary=("Render a PNG preview of the asset's current version as the next version. Without a camera in "
             "the scene one is placed to see every mesh, plus a sun if there is no light."),
    params_schema={"type": "object", "additionalProperties": False, "properties": {
        "width": {"type": "integer", "minimum": 16, "maximum": 8192, "default": 1024},
        "height": {"type": "integer", "minimum": 16, "maximum": 8192, "default": 1024},
        "engine": {"type": "string", "default": "BLENDER_WORKBENCH",
                   "description": "BLENDER_WORKBENCH (fast), BLENDER_EEVEE or CYCLES"},
        "transparent": {"type": "boolean", "default": False}}},
)
