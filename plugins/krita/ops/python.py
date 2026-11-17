from dcc_mcp.contract import OpSpec

from . import forward

SPEC = OpSpec(
    key="krita.python", backend="krita", run=forward("python"), needs=frozenset({"ui"}),
    summary=("Run Python inside Krita with the full API (docs: api.kde.org/krita). Names ready: krita, Krita, "
             "app (Krita.instance()), doc (working document; assign another Document to switch). Set "
             "'result' to return a value; print() output comes back too. Can break the document. "
             "Enabled by [krita] allow_raw."),
    params_schema={"type": "object", "required": ["code"], "additionalProperties": False,
                   "properties": {"code": {"type": "string"}}},
)
