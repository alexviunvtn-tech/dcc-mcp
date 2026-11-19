from dcc_mcp.contract import Ctx, OpResult, OpSpec

from . import DRAFT, PLACE


def run(ctx: Ctx, params: dict) -> OpResult:
    return OpResult(metrics=ctx.session.draft(params["draft"]).add_media(params))


SPEC = OpSpec(
    key="capcut.add", backend="capcut", run=run, needs=frozenset({"drafts"}), featured=True,
    summary=("Put a video, image or audio file on the timeline at 'at' seconds. Without 'track' it goes on the "
             "first track of its type with room there, else on a new track. Kept in memory until capcut.save."),
    params_schema={"type": "object", "required": ["draft", "file", "at"], "additionalProperties": False,
                   "properties": {
                       "draft": DRAFT,
                       "file": {"type": "string", "description": "absolute path on this computer"},
                       "kind": {"enum": ["video", "photo", "audio"], "description": "default: by extension"},
                       "at": {"type": "number", "minimum": 0},
                       "duration": {"type": "number", "exclusiveMinimum": 0,
                                    "description": "seconds of source to use, within the file; "
                                                   "default: to the end, image 5"},
                       "source_start": {"type": "number", "minimum": 0},
                       "track": {"type": "integer", "minimum": 0},
                       "volume": {"type": "number", "minimum": 0},
                       "speed": {"type": "number", "exclusiveMinimum": 0},
                       **PLACE}},
)
