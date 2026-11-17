from dcc_mcp.contract import OpSpec

from . import forward

SPEC = OpSpec(
    key="krita.info", backend="krita", run=forward("info"), kind="check", needs=frozenset({"ui"}),
    summary=("Working document: file, size, resolution, color space, modified flag, selection bounds and the "
             "layer tree (top first) with type, visibility, opacity 0..1, blend mode, locks, bounds."),
    params_schema={"type": "object", "additionalProperties": False},
)
