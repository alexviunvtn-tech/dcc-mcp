from dcc_mcp.contract import OpSpec

from . import forward

SPEC = OpSpec(
    key="krita.layer", backend="krita", run=forward("layer"), needs=frozenset({"ui"}),
    summary=("Layers of the working document, found by name (target; default the active layer). "
             "add (type paint|group|vector|filter|fill, parent, above), delete, rename (name), "
             "move (parent, above; no above = top), duplicate, merge_down, "
             "set (opacity 0..1, blend e.g. 'multiply', visible, locked, alpha_locked), activate."),
    params_schema={"type": "object", "required": ["action"], "additionalProperties": False, "properties": {
        "action": {"enum": ["add", "delete", "rename", "move", "duplicate", "merge_down", "set", "activate"]},
        "target": {"type": "string"},
        "name": {"type": "string"},
        "type": {"enum": ["paint", "group", "vector", "filter", "fill"], "default": "paint"},
        "parent": {"type": "string", "description": "group layer name; default the root"},
        "above": {"type": "string", "description": "place right above this layer; without it the layer goes on top"},
        "filter": {"type": "string", "description": "filter name for type=filter"},
        "generator": {"type": "string", "description": "generator for type=fill, e.g. 'color', 'pattern'"},
        "config": {"type": "object", "description": "filter or generator properties"},
        "opacity": {"type": "number", "minimum": 0, "maximum": 1},
        "blend": {"type": "string"},
        "visible": {"type": "boolean"},
        "locked": {"type": "boolean"},
        "alpha_locked": {"type": "boolean"}}},
)
