from dcc_mcp.contract import Ctx, OpResult, OpSpec

from . import DRAFT


def run(ctx: Ctx, params: dict) -> OpResult:
    dropped = ctx.session.open.pop(params["draft"], None)
    return OpResult(metrics={"discarded": bool(dropped and dropped.dirty)})


SPEC = OpSpec(
    key="capcut.discard", backend="capcut", run=run, needs=frozenset({"drafts"}),
    summary="Drop the draft's unsaved edits; the next call reads it from disk again.",
    params_schema={"type": "object", "required": ["draft"], "additionalProperties": False,
                   "properties": {"draft": DRAFT}},
)
