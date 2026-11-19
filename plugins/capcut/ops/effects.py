from dcc_mcp.contract import Ctx, OpResult, OpSpec

from . import DRAFT


def run(ctx: Ctx, params: dict) -> OpResult:
    items = ctx.session.draft(params["draft"]).library()
    out = {}
    for i in items:
        entry = {"name": i["name"], "id": i["resource_id"], "cached": i["cached"]}
        if i["kind"] == "animation":
            entry.update({"type": i["type"], "for": "text" if i["target"] == "sticker" else i["target"]})
        out.setdefault(i["kind"] + "s", []).append(entry)
    return OpResult(metrics=out)


SPEC = OpSpec(
    key="capcut.effects", backend="capcut", run=run, kind="check", needs=frozenset({"drafts"}),
    summary=("Transitions, filters, video effects and animations that capcut.apply can use: every one applied by "
             "hand in this or another draft. cached=false: CapCut's download of it is gone from its cache."),
    params_schema={"type": "object", "required": ["draft"], "additionalProperties": False,
                   "properties": {"draft": DRAFT}},
)
