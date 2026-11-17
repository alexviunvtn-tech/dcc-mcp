# DCC-MCP

One [MCP](https://modelcontextprotocol.io) server for DCC programs. The core knows nothing about any program: each program is a plugin in `plugins/`, and new operations and recipes are added as files, without touching the core.

Two plugins ship with it:

- **Krita** — through a small bridge that runs inside an open Krita window. Tested with Krita 5.3.2.1 and 5.3.4.1 on Windows.
- **Blender** — in the background: every call is its own `blender -b`, so nothing needs installing in Blender. Tested with Blender 5.2.2 LTS on Windows: import and export in all seven formats, renders in Workbench and EEVEE.

```
MCP client ──stdio──> dcc_mcp (core) ─┬─> plugins/krita/backend.py ──TCP 127.0.0.1──> dccmcp_bridge (inside Krita) ──> Krita Python API
                                      └─> plugins/blender/backend.py ──blender -b --python runner.py──> bpy
```

What the core gives every plugin:

- **Assets with versions.** `import_asset` copies a file into `work/<name>/v001_...`. Every operation that writes produces the next version (`v002_krita.kra`, `v003_krita.png`...) and a log entry in `asset.json`. Older versions stay; pass `name@v002` to work from one.
- **Recipes.** A YAML list of steps that run in order, with parameters and `on_fail: stop | warn`.
- **Sessions.** Starts the program or attaches to a running one, notices when it is gone and restarts it on the next call.
- **A fixed tool list.** The model sees about ten tools. New operations are reached through `run_operation`, so the list does not grow with every plugin.

## Why a core?

A core pays off when you use more than one program, or the same steps again and again. For one program used now and then, a plain MCP server for that program is simpler.

What it buys you:

- **Pipelines across programs.** One recipe can run a mesh through a sculpting tool, a UV tool and a painting tool. Each step reads the asset's latest version and writes the next one, so the model does not pass file paths between separate servers.
- **The same result every time.** A recipe is a fixed list of steps with parameters, so twenty files get the same treatment instead of whatever the model improvises for each.
- **History you can roll back.** The original is never overwritten; every step is a new version with its parameters and metrics in the log.
- **Plumbing written once.** Parameter checks, restarting a crashed program, refusing a second call while one runs, and readable errors live in the core, so a new plugin is a connection plus thin operations.

What it costs:

- **One process.** A broken plugin or recipe can stop the server for every program.
- **One more step for the model.** Most operations go through `run_operation`, so the model has to look them up with `list_operations` and `describe_operation` first.
- **One Python for all plugins.** If one program's library needs an older Python, every plugin runs on it.
- **Disk space.** Each version is a full copy of the file.

## Requirements

- Python 3.11 or newer
- Krita 5.x with Python plugins enabled (the default build has them), for the Krita plugin
- Blender 4.2 or newer, for the Blender plugin
- An MCP client, for example Claude Desktop

## Install

```
git clone https://github.com/alexviunvtn-tech/dcc-mcp
cd dcc-mcp
python -m pip install mcp pyyaml jsonschema pytest
python -m pytest
```

Put the bridge into Krita. Close Krita first, then:

```
python -m plugins.krita.install
```

This copies the bridge to Krita's `pykrita` folder and enables it in `kritarc` (the old file is kept as `kritarc.bak`). If the bridge does not answer after Krita starts, enable **DCC-MCP Bridge** in *Settings → Configure Krita → Python Plugin Manager* and restart Krita.

Check `dcc_mcp.toml`: `[krita] exe` must point to your Krita binary.

## Connect to Claude Desktop

Add to `mcpServers` in `claude_desktop_config.json`:

```json
"dcc-mcp": {
  "command": "C:\\Path\\To\\python.exe",
  "args": ["C:\\Path\\To\\dcc-mcp\\run_server.py"]
}
```

Use the full path to the Python you installed the packages into. Restart the client completely.

## First run

1. `start_session(backend="krita")` — starts Krita, or attaches to the one already open.
2. `import_asset(name="test", path="C:\\images\\any.png")`, then `krita_open(asset="test")` — the file opens in the window; the reply has its layer tree.
3. `run_operation(key="krita.layer", asset="test", params={"action": "add", "name": "Ink"})` — a new layer on top.
4. `krita_save(asset="test", params={"format": "png"})` — `work/test/v002_krita.png`.
5. `asset_history(asset="test")` — versions and the log of steps.

Or as a recipe: `run_recipe(name="krita_export", asset="test")` opens the asset and saves a layered `.kra` and a flat `.png`. The recipe lives in `plugins/krita/examples/`; copy it into `recipes/` to use it (every recipe in `recipes/` is checked at startup, so a recipe for a disabled plugin would stop the server).

## Tools

`list_operations`, `describe_operation`, `run_operation`, `list_recipes`, `run_recipe`, `start_session`, `stop_session`, `session_status`, `import_asset`, `asset_history`, plus a plugin's most used operations as their own tools (`krita_open`, `krita_action`, `krita_save`, `blender_info`, `blender_export`, `blender_render`).

## Krita operations

| Key | What it does |
| --- | --- |
| `krita.open` | Open an asset version in the window and make it the working document |
| `krita.new` | New canvas: size, color model, depth, profile, resolution |
| `krita.info` | Document properties, selection and the layer tree |
| `krita.layer` | Add (paint, group, vector, filter, fill), delete, rename, move, duplicate, merge down, set opacity/blend/visibility/locks, activate |
| `krita.filter` | Apply a filter with its settings to a layer or the selection |
| `krita.action` | Trigger any menu command or tool by its action name |
| `krita.catalog` | What this Krita has: actions, filters, brush presets, color models, profiles |
| `krita.save` | Save the next version: `kra` keeps everything; `psd`, `png`, `jpg`, `tif`, `exr`, `tga`, `webp`, `jxl` are exports |
| `krita.python` | Any Python inside Krita with the full API. Off unless `allow_raw = true` |

For a new canvas with nothing to import, import `plugins/krita/blank.png` (1×1) as the asset, run `krita.new`, then `krita.save` on that asset.

## Blender operations

Each step reads the asset's current version: a `.blend` opens; `fbx`, `obj`, `glb`/`gltf`, `usd`, `stl` and `ply` are imported into an empty scene. Set `[blender] exe` in `dcc_mcp.toml`; nothing else to install.

| Key | What it does |
| --- | --- |
| `blender.info` | Objects with type, size, vertices, faces, triangles, UV layers, materials, plus totals. A check: fails above `max_triangles` |
| `blender.save` | Save as a `.blend`: the next version |
| `blender.export` | Export the next version: `glb` (default), `gltf`, `fbx`, `obj`, `usd`, `stl`, `ply`. `options` go to the exporter as keyword arguments |
| `blender.render` | PNG preview: the next version. Without a camera one is placed to see every mesh, plus a sun if there is no light. Workbench by default; `BLENDER_EEVEE` or `CYCLES` on request |
| `blender.python` | Any bpy script, then the scene is saved as the next `.blend`. Off unless `allow_raw = true` |

![Suzanne rendered by blender.render with EEVEE](docs/blender_render_example.png)

*`blender.render` with `engine: BLENDER_EEVEE` on a scene with no camera or light: both were placed automatically.*

Recipe example: `plugins/blender/examples/blender_preview.yaml` — polycount check, `.blend`, GLB, preview PNG. Copy it into `recipes/` to use it. A rendered PNG is a version too, and Blender cannot open it, so put renders last or run the next step on `name@vNNN`.

## Security

- The bridge listens on `127.0.0.1` only, on a port the OS picks. Every request must carry a token that Krita writes to `krita/dccmcp_bridge.json` in your user profile; it changes on every Krita start.
- `krita.python` and `blender.python` run any code the model sends. They are off by default; turn them on in `dcc_mcp.toml` only if you want that.
- Asset names are checked so files stay inside the work folder.

## Extending

- **Operation:** a file in `plugins/<program>/ops/` with `SPEC = OpSpec(...)` and one line in the plugin's `register`. For Krita, the logic goes into a `cmd_<name>` method of `bridge/dccmcp_bridge/commands.py` and the op only forwards (`forward("<name>")`); run the installer again afterwards. Try the idea through `krita.python` first.
- **Recipe:** a file in `recipes/<name>.yaml`, see `plugins/krita/examples/krita_export.yaml`.
- **Program:** a folder `plugins/<name>/` with a backend that follows `dcc_mcp/contract.py` and a `register(registry, cfg)` function, then the name in `plugins` in `dcc_mcp.toml`. Plugins may import only the core, never each other; `tests/test_architecture.py` checks this.

## Limits

- Krita works only with an open window (`live`); there is no headless mode yet.
- Blender works only in the background: no live window yet, and every call starts Blender again, which costs a few seconds.
- The model gets JSON back, not a picture of the canvas.
- Windows is the tested platform. The code has Linux paths for the bridge and installer, but they are untested.

## License

Apache License 2.0, see [LICENSE](LICENSE).
