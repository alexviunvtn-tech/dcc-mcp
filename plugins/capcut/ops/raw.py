from dcc_mcp.contract import Ctx, OpResult, OpSpec

from . import DRAFT


def run(ctx: Ctx, params: dict) -> OpResult:
    return OpResult(metrics=ctx.session.draft(params["draft"]).raw_patch(params["patch"]))


SPEC = OpSpec(
    key="capcut.raw", backend="capcut", run=run, needs=frozenset({"drafts"}),
    summary=("Deep-merge a JSON patch into the draft's draft_content (lists are replaced whole). For trying "
             "fields before they become operations; can break the draft. Enabled by [capcut] allow_raw."),
    params_schema={"type": "object", "required": ["draft", "patch"], "additionalProperties": False,
                   "properties": {"draft": DRAFT, "patch": {"type": "object"}}},
)
