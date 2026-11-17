from dcc_mcp.contract import Ctx, OpResult, OpSpec


def run(ctx: Ctx, params: dict) -> OpResult:
    m = ctx.session.call("info", ctx.input_path)
    limit = params.get("max_triangles")
    if limit is not None and m["triangles"] > limit:
        return OpResult("fail", metrics=m, notes=f"{m['triangles']} triangles > {limit}")
    return OpResult(metrics=m)


SPEC = OpSpec(
    key="blender.info", backend="blender", run=run, kind="check", needs=frozenset({"bpy"}), featured=True,
    summary=("Objects of the asset's current version (a .blend opens, mesh files are imported): type, size, "
             "vertices, faces, triangles, UV layers, materials, plus totals. Fails above max_triangles."),
    params_schema={"type": "object", "additionalProperties": False,
                   "properties": {"max_triangles": {"type": "integer", "minimum": 1}}},
)
