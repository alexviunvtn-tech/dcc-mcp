from pathlib import Path

from dcc_mcp.contract import OpSpec

from . import forward

BLANK = Path(__file__).resolve().parent.parent / "blank.png"

SPEC = OpSpec(
    key="krita.new", backend="krita", run=forward("new"), needs=frozenset({"ui"}),
    summary=("New canvas in the Krita window as the working document. To keep it, save it into an asset: "
             f"import_asset(name, '{BLANK}') first, then krita.save on it. "
             "Color models/depths/profiles: krita.catalog."),
    params_schema={"type": "object", "required": ["width", "height"], "additionalProperties": False,
                   "properties": {
                       "width": {"type": "integer", "minimum": 1, "maximum": 100000},
                       "height": {"type": "integer", "minimum": 1, "maximum": 100000},
                       "name": {"type": "string", "default": "untitled"},
                       "color_model": {"type": "string", "default": "RGBA",
                                       "description": "RGBA, GRAYA, CMYKA, LABA, XYZA, YCbCrA"},
                       "color_depth": {"type": "string", "default": "U8", "description": "U8, U16, F16, F32"},
                       "profile": {"type": "string", "default": "", "description": "empty = Krita's default"},
                       "resolution": {"type": "number", "exclusiveMinimum": 0, "default": 300}}},
)
