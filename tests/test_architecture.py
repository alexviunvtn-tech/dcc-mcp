"""Dependency rules: plugin -> core only; core never imports a plugin; plugins never import each other."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def imports(folder: Path) -> set[tuple[str, str]]:
    found = set()
    for path in folder.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found |= {(str(path), a.name) for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add((str(path), node.module))
    return found


def test_core_does_not_import_plugins():
    bad = {(f, m) for f, m in imports(ROOT / "dcc_mcp") if m.split(".")[0] == "plugins"}
    assert not bad


def test_plugins_do_not_import_each_other():
    for plugin in (p for p in (ROOT / "plugins").iterdir() if p.is_dir()):
        bad = {(f, m) for f, m in imports(plugin)
               if m.startswith("plugins.") and not m.startswith(f"plugins.{plugin.name}")}
        assert not bad, bad
