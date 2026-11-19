from dcc_mcp.contract import Ctx, OpResult, OpSpec

from . import DRAFT


def run(ctx: Ctx, params: dict) -> OpResult:
    name, force = params["draft"], params.get("force", False)
    if name not in ctx.session.open or not ctx.session.open[name].dirty:
        ctx.session.folder(name)  # an unknown draft still fails as one
        return OpResult("warn", notes=f"no unsaved edits in {name!r}: nothing written. Edits made before a "
                                      "dcc-mcp restart are lost: redo them, then save")
    blockers = ctx.session.blockers(name, force)
    if blockers:
        return OpResult("fail", notes="; ".join(blockers))
    draft = ctx.session.draft(name)
    report = draft.validate()
    if not report["ok"] and not force:
        return OpResult("fail", metrics=report, notes="not saved, fix first (or force=true): "
                        + "; ".join(report["issues"][:5]))
    result = draft.save()
    del ctx.session.open[name]  # next call reads what CapCut will read
    return OpResult("ok" if report["ok"] else "warn", metrics={**result, "validation": report},
                    notes="open the draft in CapCut to see the result")


SPEC = OpSpec(
    key="capcut.save", backend="capcut", run=run, needs=frozenset({"drafts"}), featured=True,
    summary=("Write the draft's edits to disk where CapCut reads them (backup in <draft>/.dccmcp_backup). "
             "Refuses while the draft is open in CapCut, while CapCut runs, or if capcut.validate finds issues; "
             "force=true skips the last two. Without unsaved edits it writes nothing."),
    params_schema={"type": "object", "required": ["draft"], "additionalProperties": False,
                   "properties": {"draft": DRAFT, "force": {"type": "boolean", "default": False}}},
)
