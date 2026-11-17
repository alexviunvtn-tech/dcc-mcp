"""Asset files belong to the core: plugins get paths, never rename or delete anything."""
from __future__ import annotations

import json
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

_NAME = re.compile(r"[A-Za-z0-9_.-]+")


class AssetError(ValueError):
    pass


class AssetStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()

    def _dir(self, name: str) -> Path:
        # trust boundary: names come from the model, keep them inside work_dir
        if not _NAME.fullmatch(name) or name in (".", ".."):
            raise AssetError(f"bad asset name {name!r}: use letters, digits, '_', '-', '.'")
        return self.root / name

    def _meta(self, name: str) -> dict:
        path = self._dir(name) / "asset.json"
        if not path.exists():
            raise AssetError(f"asset {name!r} not found; import it first")
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, name: str, meta: dict) -> None:
        text = json.dumps(meta, ensure_ascii=False, indent=2, default=str)
        (self._dir(name) / "asset.json").write_text(text, encoding="utf-8")

    def import_file(self, name: str, src: Path) -> dict:
        folder = self._dir(name)
        if folder.exists():
            raise AssetError(f"asset {name!r} already exists")
        if not src.is_file():
            raise AssetError(f"file not found: {src}")
        folder.mkdir(parents=True)
        dst = folder / f"v001_{src.name}"
        shutil.copy2(src, dst)
        meta = {"source": str(src), "versions": [dst.name], "history": [], "manual_edit": False}
        self._save(name, meta)
        return {"asset": name, "version": 1, "file": str(dst)}

    def resolve(self, ref: str) -> tuple[str, Path]:
        """'name' -> latest version, 'name@v002' -> that version."""
        name, _, ver = ref.partition("@")
        versions = self._meta(name)["versions"]
        if not ver:
            return name, self._dir(name) / versions[-1]
        if not re.fullmatch(r"v\d{3}", ver) or int(ver[1:]) > len(versions) or ver == "v000":
            raise AssetError(f"asset {name!r} has no version {ver!r}")
        return name, self._dir(name) / versions[int(ver[1:]) - 1]

    def next_path(self, name: str, tag: str, ext: str) -> Path:
        n = len(self._meta(name)["versions"]) + 1
        return self._dir(name) / f"v{n:03d}_{tag}.{ext.lstrip('.')}"

    def commit(self, name: str, files: list[str], record: dict) -> None:
        with self._lock:
            meta = self._meta(name)
            for f in files:
                path = Path(f)
                if path.parent.resolve() != self._dir(name).resolve() or not path.exists():
                    raise AssetError(f"operation reported a file outside the asset folder or missing: {f}")
                meta["versions"].append(path.name)
                meta["manual_edit"] = False
            record = {**record, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "output": [Path(f).name for f in files]}
            meta["history"].append(record)
            self._save(name, meta)

    def mark_manual_edit(self, name: str) -> None:
        with self._lock:
            meta = self._meta(name)
            meta["manual_edit"] = True
            self._save(name, meta)

    def info(self, name: str) -> dict:
        return self._meta(name)
