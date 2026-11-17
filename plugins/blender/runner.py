"""Runs inside Blender, started by backend.py:

    blender -b --factory-startup --python runner.py -- request.json result.json

One request in, one result out. Every call is a fresh Blender, so state lives only in files.
"""
import contextlib
import io
import json
import math
import sys
import traceback
from pathlib import Path

import bpy

# file extension -> operator that imports it into an empty scene
IMPORTERS = {
    ".fbx": "import_scene.fbx", ".glb": "import_scene.gltf", ".gltf": "import_scene.gltf",
    ".obj": "wm.obj_import", ".usd": "wm.usd_import", ".usda": "wm.usd_import", ".usdc": "wm.usd_import",
    ".usdz": "wm.usd_import", ".stl": "wm.stl_import", ".ply": "wm.ply_import",
}
# format -> (operator, default options)
EXPORTERS = {
    "fbx": ("export_scene.fbx", {}),
    "glb": ("export_scene.gltf", {"export_format": "GLB"}),
    "gltf": ("export_scene.gltf", {"export_format": "GLTF_SEPARATE"}),
    "obj": ("wm.obj_export", {}),
    "usd": ("wm.usd_export", {}),
    "stl": ("wm.stl_export", {}),
    "ply": ("wm.ply_export", {}),
}


class Refused(Exception):
    """Expected failure with a message for the model."""


def op(path):
    module, name = path.split(".")
    try:
        operator = getattr(getattr(bpy.ops, module), name)
        operator.get_rna_type()  # bpy.ops returns unknown operators lazily; fail early with a clear message
    except (AttributeError, KeyError) as e:
        raise Refused(f"this Blender ({bpy.app.version_string}) has no operator bpy.ops.{path}") from e
    return operator


def load(path):
    """Open a .blend, or import a mesh file into an empty scene."""
    if path is None:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        return
    ext = Path(path).suffix.lower()
    if ext == ".blend":
        bpy.ops.wm.open_mainfile(filepath=path)
        return
    if ext not in IMPORTERS:
        raise Refused(f"Blender cannot open {ext} files (works: .blend {' '.join(sorted(IMPORTERS))}); "
                      "run the step on an earlier version: name@vNNN")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    op(IMPORTERS[ext])(filepath=path)


def info():
    scene = bpy.context.scene
    items, triangles = [], 0
    for ob in scene.objects:
        item = {"name": ob.name, "type": ob.type, "dimensions": [round(v, 4) for v in ob.dimensions]}
        if ob.type == "MESH":
            mesh = ob.data
            tris = sum(len(p.vertices) - 2 for p in mesh.polygons)  # base mesh, modifiers not applied
            item.update(vertices=len(mesh.vertices), faces=len(mesh.polygons), triangles=tris,
                        uv_layers=[uv.name for uv in mesh.uv_layers],
                        materials=[m.name for m in mesh.materials if m])
            triangles += tris
        items.append(item)
    return {"blender": bpy.app.version_string, "objects": len(items), "triangles": triangles,
            "unit_scale": scene.unit_settings.scale_length, "items": items[:500]}


def frame_scene(scene):
    """Add a camera that sees every mesh, and a sun if there is no light."""
    from mathutils import Vector

    meshes = [o for o in scene.objects if o.type == "MESH"]
    if not meshes:
        raise Refused("nothing to render: the scene has no mesh objects")
    points = [o.matrix_world @ Vector(corner) for o in meshes for corner in o.bound_box]
    lo = Vector([min(p[i] for p in points) for i in range(3)])
    hi = Vector([max(p[i] for p in points) for i in range(3)])
    center, radius = (lo + hi) / 2, max((hi - lo).length / 2, 1e-4)

    cam_data = bpy.data.cameras.new("dccmcp_camera")
    cam = bpy.data.objects.new("dccmcp_camera", cam_data)
    scene.collection.objects.link(cam)
    distance = radius / math.sin(cam_data.angle / 2) * 1.1  # the bounding sphere fits the view
    cam.location = center + Vector((1.0, -1.0, 0.7)).normalized() * distance
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam_data.clip_start, cam_data.clip_end = distance / 1000, distance + radius * 4
    scene.camera = cam

    if not any(o.type == "LIGHT" for o in scene.objects):
        sun = bpy.data.objects.new("dccmcp_sun", bpy.data.lights.new("dccmcp_sun", "SUN"))
        sun.rotation_euler = (math.radians(50), 0.0, math.radians(30))
        scene.collection.objects.link(sun)


def render(output, width=1024, height=1024, engine="BLENDER_WORKBENCH", transparent=False):
    scene = bpy.context.scene
    if scene.camera is None:
        frame_scene(scene)
    if scene.world is None:  # an imported mesh comes without one; EEVEE and Cycles would render on black
        scene.world = bpy.data.worlds.new("dccmcp_world")
        scene.world.color = (0.8, 0.8, 0.8)
    r = scene.render
    r.engine = engine
    r.resolution_x, r.resolution_y, r.resolution_percentage = width, height, 100
    r.film_transparent = transparent
    r.image_settings.file_format = "PNG"
    r.filepath = output
    bpy.ops.render.render(write_still=True)
    return {"file": output, "engine": engine, "size": [width, height]}


def plain(value):
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


def handle(req):
    cmd, args, output = req["cmd"], req.get("args") or {}, req.get("output")
    if cmd == "ping":
        return {"version": bpy.app.version_string}
    load(req.get("input"))
    if cmd == "info":
        return info()
    if cmd == "save":
        bpy.ops.wm.save_as_mainfile(filepath=output)
        return {"file": output}
    if cmd == "export":
        fmt = args["format"]
        if fmt not in EXPORTERS:
            raise Refused(f"unknown export format {fmt!r}; works: {', '.join(EXPORTERS)}")
        path, defaults = EXPORTERS[fmt]
        op(path)(filepath=output, **{**defaults, **(args.get("options") or {})})
        return {"file": output, "format": fmt}
    if cmd == "render":
        return render(output, **args)
    if cmd == "python":
        ns = {"bpy": bpy, "result": None}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            exec(compile(args["code"], "<blender.python>", "exec"), ns)
        bpy.ops.wm.save_as_mainfile(filepath=output)
        return {"result": plain(ns["result"]), "stdout": out.getvalue()[-20000:], "file": output}
    raise Refused(f"unknown command {cmd!r}")


def main():
    req_path, res_path = sys.argv[sys.argv.index("--") + 1:][:2]
    try:
        reply = {"ok": True, "result": handle(json.loads(Path(req_path).read_text(encoding="utf-8")))}
    except Refused as e:
        reply = {"ok": False, "error": str(e)}
    except Exception as e:  # operator errors arrive as RuntimeError with Blender's message
        reply = {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc(limit=5)}
    Path(res_path).write_text(json.dumps(reply, default=repr), encoding="utf-8")


if __name__ == "__main__":
    main()
