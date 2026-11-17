from dcc_mcp.contract import Ctx, OpResult, OpSpec

FORMATS = ["glb", "gltf", "fbx", "obj", "usd", "stl", "ply"]


def run(ctx: Ctx, params: dict) -> OpResult:
    fmt = params.get("format", "glb")
    out = ctx.new_version_path(fmt)
    ctx.session.call("export", ctx.input_path, out, {"format": fmt, "options": params.get("options", {})})
    return OpResult(files=[str(out)])


SPEC = OpSpec(
    key="blender.export", backend="blender", run=run, needs=frozenset({"bpy"}), featured=True,
    summary=("Export the asset's current version as the next version: glb (default), gltf, fbx, obj, usd, stl, "
             "ply. options go to the exporter as keyword arguments, e.g. {'export_apply': true} for glTF."),
    params_schema={"type": "object", "additionalProperties": False, "properties": {
        "format": {"enum": FORMATS, "default": "glb"},
        "options": {"type": "object", "description": "exporter keyword arguments, see Blender's bpy.ops docs"}}},
)
