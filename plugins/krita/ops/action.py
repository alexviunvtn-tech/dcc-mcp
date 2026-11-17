from dcc_mcp.contract import OpSpec

from . import forward

SPEC = OpSpec(
    key="krita.action", backend="krita", run=forward("action"), needs=frozenset({"ui"}), featured=True,
    summary=("Trigger any Krita menu command or tool by its action name, e.g. 'flatten_image', "
             "'select_all', 'mirror_canvas', 'KritaShape/KisToolBrush'. Find names with krita.catalog "
             "kind=actions contains=<word>. Commands that open a dialog wait for the user in the window."),
    params_schema={"type": "object", "required": ["name"], "additionalProperties": False,
                   "properties": {"name": {"type": "string"}}},
)
