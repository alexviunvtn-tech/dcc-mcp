from dcc_mcp.contract import Ctx, OpResult, OpSpec

from . import DRAFT, PLACE


def run(ctx: Ctx, params: dict) -> OpResult:
    return OpResult(metrics=ctx.session.draft(params["draft"]).add_text(params))


SPEC = OpSpec(
    key="capcut.text", backend="capcut", run=run, needs=frozenset({"drafts"}), featured=True,
    summary=("Add a text layer at 'at' seconds. Font and style are copied from an existing text layer in this "
             "or another draft (make one in CapCut once). Kept in memory until capcut.save."),
    params_schema={"type": "object", "required": ["draft", "text", "at"], "additionalProperties": False,
                   "properties": {
                       "draft": DRAFT,
                       "text": {"type": "string", "minLength": 1},
                       "at": {"type": "number", "minimum": 0},
                       "duration": {"type": "number", "exclusiveMinimum": 0, "default": 3},
                       "track": {"type": "integer", "minimum": 0},
                       "font_size": {"type": "number", "exclusiveMinimum": 0},
                       "color": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
                       **PLACE}},
)
