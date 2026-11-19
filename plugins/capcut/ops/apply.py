from dcc_mcp.contract import Ctx, OpResult, OpSpec

from . import DRAFT


def run(ctx: Ctx, params: dict) -> OpResult:
    return OpResult(metrics=ctx.session.draft(params["draft"]).apply_effect(params))


SPEC = OpSpec(
    key="capcut.apply", backend="capcut", run=run, needs=frozenset({"drafts"}), featured=True,
    summary=("Put a transition (at the end of the segment, before the next clip), filter, video effect or "
             "animation (in/out/loop, text or video) on a segment, by name from capcut.effects. A new transition "
             "or filter replaces the segment's old one. Kept in memory until capcut.save."),
    params_schema={"type": "object", "required": ["draft", "segment", "kind", "name"], "additionalProperties": False,
                   "properties": {
                       "draft": DRAFT,
                       "segment": {"type": "string"},
                       "kind": {"enum": ["transition", "filter", "effect", "animation"]},
                       "name": {"type": "string", "description": "name or id from capcut.effects"},
                       "duration": {"type": "number", "exclusiveMinimum": 0,
                                    "description": "seconds; transitions and animations only"}}},
)
