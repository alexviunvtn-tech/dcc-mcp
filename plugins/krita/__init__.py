from .backend import KritaBackend
from .ops import action, catalog, filter, info, layer, new, open, python, save


def register(registry, cfg: dict) -> None:
    registry.add_backend("krita", lambda: KritaBackend(cfg))
    for op in (open, new, info, layer, filter, action, catalog, save):
        registry.add_op(op.SPEC)
    if cfg.get("allow_raw", False):
        registry.add_op(python.SPEC)
