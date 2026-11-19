from dcc_mcp.contract import Ctx, OpResult, OpSpec

from ..draft import DraftError, main_timeline, read_json


def run(ctx: Ctx, params: dict) -> OpResult:
    drafts = []
    for folder in sorted(ctx.session.root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        item = {"name": folder.name, "open_in_capcut": (folder / ".locked").exists(),
                "unsaved_edits": folder.name in ctx.session.open and ctx.session.open[folder.name].dirty}
        try:
            c = read_json(main_timeline(folder))
            item.update(duration=c.get("duration", 0) / 1e6, tracks=len(c.get("tracks", [])),
                        app_version=(c.get("platform") or {}).get("app_version"))
        except (DraftError, OSError, ValueError) as e:
            item["error"] = str(e)
        drafts.append(item)
    return OpResult(metrics={"drafts_dir": str(ctx.session.root), "drafts": drafts})


SPEC = OpSpec(
    key="capcut.list", backend="capcut", run=run, kind="check", needs=frozenset({"drafts"}),
    summary="CapCut drafts (newest first): name, length in seconds, tracks, CapCut version, open in CapCut.",
    params_schema={"type": "object", "additionalProperties": False},
)
