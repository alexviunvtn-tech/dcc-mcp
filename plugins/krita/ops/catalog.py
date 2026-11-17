from dcc_mcp.contract import OpSpec

from . import forward

SPEC = OpSpec(
    key="krita.catalog", backend="krita", run=forward("catalog"), kind="check", needs=frozenset({"ui"}),
    summary=("What this Krita has: actions (name + menu text), filters, brush_presets, color_models "
             "(with depths), profiles (for model+depth). contains filters by substring, limit caps the list."),
    params_schema={"type": "object", "required": ["kind"], "additionalProperties": False, "properties": {
        "kind": {"enum": ["actions", "filters", "brush_presets", "color_models", "profiles"]},
        "contains": {"type": "string"},
        "model": {"type": "string", "default": "RGBA"},
        "depth": {"type": "string", "default": "U8"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 200}}},
)
