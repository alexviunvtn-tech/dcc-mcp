from dcc_mcp.contract import OpSpec

from . import forward

SPEC = OpSpec(
    key="krita.filter", backend="krita", run=forward("filter"), needs=frozenset({"ui"}),
    summary=("Apply a filter (names: krita.catalog kind=filters) to a layer (target; default active), "
             "inside the selection if there is one and selection_only is true. config sets the filter's "
             "properties; the reply lists all of them, so call once to learn the keys."),
    params_schema={"type": "object", "required": ["name"], "additionalProperties": False, "properties": {
        "name": {"type": "string"},
        "config": {"type": "object"},
        "target": {"type": "string"},
        "selection_only": {"type": "boolean", "default": True}}},
)
