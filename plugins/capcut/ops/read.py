from dcc_mcp.contract import Ctx, OpResult, OpSpec

from . import DRAFT


def run(ctx: Ctx, params: dict) -> OpResult:
    return OpResult(metrics=ctx.session.draft(params["draft"]).timeline())


SPEC = OpSpec(
    key="capcut.read", backend="capcut", run=run, kind="check", needs=frozenset({"drafts"}), featured=True,
    summary=("Timeline of a draft, including unsaved edits: canvas, fps, tracks by index and every segment "
             "(id, kind, media file name or text, full file path, at/duration/source_start in seconds, speed, "
             "volume, scale/pos_x/pos_y/rotation/opacity, effects)."),
    params_schema={"type": "object", "required": ["draft"], "additionalProperties": False,
                   "properties": {"draft": DRAFT}},
)
