from dcc_mcp.contract import Ctx, OpResult, OpSpec


def run(ctx: Ctx, params: dict) -> OpResult:
    if ctx.input_path is None:
        return OpResult("fail", notes="krita.open needs an asset")
    return OpResult(metrics=ctx.session.call("open", {"path": str(ctx.input_path.resolve())}))


SPEC = OpSpec(
    key="krita.open", backend="krita", run=run, needs=frozenset({"ui"}), featured=True,
    summary=("Open the asset's current version (or name@v00N) in the Krita window and make it the working "
             "document; returns its size, color space and layer tree."),
    params_schema={"type": "object", "additionalProperties": False},
)
