from dcc_mcp.contract import Ctx, OpResult, OpSpec


def run(ctx: Ctx, params: dict) -> OpResult:
    fmt = params.get("format", "kra")
    path = ctx.new_version_path(fmt)
    ctx.session.call("save", {"path": str(path.resolve()), "format": fmt})
    return OpResult(files=[str(path)])


SPEC = OpSpec(
    key="krita.save", backend="krita", run=run, needs=frozenset({"ui"}), featured=True,
    summary=("Save the working document as the asset's next version. kra keeps everything and the window "
             "keeps working on the new file; other formats are an export and the window stays on its .kra."),
    params_schema={"type": "object", "additionalProperties": False, "properties": {
        "format": {"enum": ["kra", "psd", "png", "jpg", "tif", "exr", "tga", "webp", "jxl"], "default": "kra"}}},
)
