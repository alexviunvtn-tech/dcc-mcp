from dcc_mcp.contract import Ctx, OpResult, OpSpec

from . import DRAFT


def run(ctx: Ctx, params: dict) -> OpResult:
    report = ctx.session.draft(params["draft"]).validate()
    return OpResult("ok" if report["ok"] else "fail", metrics=report, notes="; ".join(report["issues"][:5]))


SPEC = OpSpec(
    key="capcut.validate", backend="capcut", run=run, kind="check", needs=frozenset({"drafts"}),
    summary=("Check a draft (with unsaved edits): duplicate ids, missing materials or media files, bad or "
             "overlapping time ranges, clips using more than their file, gaps on the magnetic main track."),
    params_schema={"type": "object", "required": ["draft"], "additionalProperties": False,
                   "properties": {"draft": DRAFT}},
)
