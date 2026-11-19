from dcc_mcp.contract import Ctx, OpResult, OpSpec

from . import DRAFT, PLACE


def run(ctx: Ctx, params: dict) -> OpResult:
    return OpResult(metrics=ctx.session.draft(params["draft"]).edit(params))


SPEC = OpSpec(
    key="capcut.edit", backend="capcut", run=run, needs=frozenset({"drafts"}), featured=True,
    summary=("Change a segment (id from capcut.read): move (at, track), trim (at, duration, source_start), "
             "split (at = timeline time inside it), delete, set (scale, pos_x, pos_y, rotation, opacity, volume, "
             "speed, visible). Times in seconds. Kept in memory until capcut.save."),
    params_schema={"type": "object", "required": ["draft", "segment", "action"], "additionalProperties": False,
                   "allOf": [{"if": {"properties": {"action": {"const": "split"}}}, "then": {"required": ["at"]}}],
                   "properties": {
                       "draft": DRAFT,
                       "segment": {"type": "string"},
                       "action": {"enum": ["move", "trim", "split", "delete", "set"]},
                       "at": {"type": "number", "minimum": 0},
                       "track": {"type": "integer", "minimum": 0},
                       "duration": {"type": "number", "exclusiveMinimum": 0},
                       "source_start": {"type": "number", "minimum": 0},
                       "volume": {"type": "number", "minimum": 0},
                       "speed": {"type": "number", "exclusiveMinimum": 0},
                       "visible": {"type": "boolean"},
                       **PLACE}},
)
