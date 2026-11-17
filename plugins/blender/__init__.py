from .backend import BlenderBackend
from .ops import export, info, python, render, save


def register(registry, cfg: dict) -> None:
    registry.add_backend("blender", lambda: BlenderBackend(cfg))
    for op in (info, save, export, render):
        registry.add_op(op.SPEC)
    if cfg.get("allow_raw", False):
        registry.add_op(python.SPEC)
