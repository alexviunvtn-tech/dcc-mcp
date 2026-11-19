from .backend import CapCutBackend
from .ops import add, apply, discard, edit, effects, list, raw, read, save, text, validate


def register(registry, cfg: dict) -> None:
    registry.add_backend("capcut", lambda: CapCutBackend(cfg))
    for op in (list, read, add, text, edit, effects, apply, validate, save, discard):
        registry.add_op(op.SPEC)
    if cfg.get("allow_raw", False):
        registry.add_op(raw.SPEC)
