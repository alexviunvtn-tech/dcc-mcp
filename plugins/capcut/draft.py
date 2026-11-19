"""CapCut desktop draft (project folder) as JSON: read, edit in memory, save.

Layout checked on CapCut 9.8.0 Windows (2026-11-17): the app reads
Timelines/<main_timeline_id>/draft_content.json (main_timeline_id is in Timelines/project.json);
the root draft_content.json and both template-2.tmp files are mirrors it rewrites on save.
New segments and materials are cloned from real ones (this draft first, then other drafts):
CapCut's format is undocumented and a hand-built object is easy to get wrong.
"""
from __future__ import annotations

import copy
import json
import math
import os
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

US = 1_000_000
PHOTO_MATERIAL_US = 10_800 * US  # CapCut gives a still image a 3 h material length
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
# extra materials a media clip may keep from its template; anything else (transitions, filters,
# animations of the template clip) would leak the template's look into the new clip
MEDIA_REFS = {"speeds", "placeholder_infos", "canvases", "sound_channel_mappings", "material_colors",
              "vocal_separations", "beats", "loudnesses"}
SOURCE_FIELDS = ("media_path", "local_id", "material_id", "material_url", "origin_material_id", "request_id",
                 "aigc_history_id", "aigc_item_id", "team_id", "formula_id", "unique_id", "reverse_path",
                 "intensifies_path", "reverse_intensifies_path", "intensifies_audio_path", "cartoon_path",
                 "music_id", "source_platform_id")
POOL_TYPE = {"video": "video", "photo": "photo", "audio": "music"}  # draft_meta_info metetype


class DraftError(ValueError):
    pass


def uid() -> str:
    return str(uuid.uuid4()).upper()


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2  # CapCut text style ranges count UTF-16 units


def kind_of(path: str) -> str:
    ext = Path(path).suffix.lower()
    return "photo" if ext in IMAGE_EXT else "audio" if ext in AUDIO_EXT else "video"


def read_json(path: Path) -> dict:
    raw = path.read_bytes()
    if not raw.lstrip().startswith(b"{"):
        raise DraftError(f"{path.name} is not plain JSON (encrypted draft, e.g. JianYing 6+): not supported")
    return json.loads(raw.decode("utf-8-sig"))


def write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".dccmcp.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)  # atomic on the same volume


def main_timeline(folder: Path) -> Path:
    """The file CapCut reads; drafts from before the Timelines layout keep it at the root."""
    project = folder / "Timelines" / "project.json"
    if project.exists():
        main = read_json(project).get("main_timeline_id")
        nested = folder / "Timelines" / str(main) / "draft_content.json"
        if main and nested.exists():
            return nested
    root = folder / "draft_content.json"
    if not root.exists():
        raise DraftError(f"no draft_content.json in {folder}")
    return root


def find_material(content: dict, mid: str) -> tuple[str | None, dict | None]:
    for key, items in content.get("materials", {}).items():
        if isinstance(items, list):
            for m in items:
                if isinstance(m, dict) and m.get("id") == mid:
                    return key, m
    return None, None


def segments(content: dict):
    for i, track in enumerate(content.get("tracks", [])):
        for seg in track.get("segments", []):
            yield i, track, seg


class Draft:
    def __init__(self, folder: Path, probe: Callable[[str], dict], others: Callable[[], list[Path]]) -> None:
        self.folder = folder
        self.path = main_timeline(folder)
        self.content = read_json(self.path)
        self.meta_path = folder / "draft_meta_info.json"
        self.meta = read_json(self.meta_path) if self.meta_path.exists() else None
        self._probe = probe
        self._others = others  # folders of other drafts, searched for templates
        self._templates: dict = {}
        self._pool: list[dict] = []  # media-pool entries to add to draft_meta_info on save
        self.dirty = False

    # ---------- read ----------
    def timeline(self) -> dict:
        c = self.content
        tracks = []
        for i, track in enumerate(c.get("tracks", [])):
            segs = []
            for seg in track.get("segments", []):
                key, m = find_material(c, seg.get("material_id"))
                label = None
                if m:
                    if key == "texts":
                        label = _text_of(m)
                    else:
                        label = m.get("material_name") or Path(m.get("path", "")).name or m.get("type")
                t, s = seg["target_timerange"], seg.get("source_timerange") or {}
                item = {"id": seg["id"], "kind": m.get("type") if m else None, "media": label,
                        "at": t["start"] / US, "duration": t["duration"] / US,
                        "source_start": (s.get("start") or 0) / US, "speed": seg.get("speed", 1.0),
                        "visible": seg.get("visible", True)}
                if m and key in ("videos", "audios"):
                    item["file"] = m.get("path")
                if seg.get("source_timerange") is not None and item["kind"] != "photo":  # text, photo: no sound
                    item["volume"] = seg.get("volume", 1.0)
                clip = seg.get("clip")
                if clip:
                    pos = clip.get("transform") or {}
                    item.update(scale=(clip.get("scale") or {}).get("x", 1.0), pos_x=pos.get("x", 0.0),
                                pos_y=pos.get("y", 0.0), rotation=clip.get("rotation", 0.0),
                                opacity=clip.get("alpha", 1.0))
                item["effects"] = _effect_names(c, seg)
                segs.append(item)
            tracks.append({"index": i, "type": track.get("type"), "segments": segs})
        canvas = c.get("canvas_config") or {}
        return {"file": str(self.path), "app_version": (c.get("platform") or {}).get("app_version"),
                "duration": c.get("duration", 0) / US, "fps": c.get("fps"),
                "canvas": [canvas.get("width"), canvas.get("height")], "unsaved_edits": self.dirty,
                "tracks": tracks}

    # ---------- templates ----------
    def _template(self, kind: str) -> dict:
        """One real segment of this kind with its material and extra materials, deep-copied."""
        if kind not in self._templates:
            found = _harvest(self.content, kind)
            for folder in ([] if found else self._others()):
                try:
                    found = _harvest(read_json(main_timeline(folder)), kind)
                except (DraftError, OSError, ValueError):
                    continue
                if found:
                    break
            if found is None and kind == "photo":
                found = self._template("video")
            if found is None:
                hint = "a text layer" if kind == "text" else f"a {kind} clip"
                raise DraftError(f"no {kind} template: add {hint} to any CapCut draft once (CapCut writes its "
                                 "format there), then try again")
            self._templates[kind] = found
        return copy.deepcopy(self._templates[kind])

    def _place(self, tpl: dict, mat_key: str, mat: dict, at: int, dur: int, src: int, params: dict,
               track_type: str, keep_refs: Callable[[str], bool]) -> dict:
        self.content["materials"].setdefault(mat_key, []).append(mat)
        refs = []
        for key, ref in tpl["refs"]:
            if keep_refs(key):
                ref["id"] = uid()
                self.content["materials"].setdefault(key, []).append(ref)
                refs.append(ref["id"])
        seg = tpl["seg"]
        seg.update(id=uid(), material_id=mat["id"], extra_material_refs=refs, keyframe_refs=[],
                   common_keyframes=[], group_id="", raw_segment_id="", visible=True, speed=1.0, volume=1.0,
                   target_timerange={"start": at, "duration": dur},
                   source_timerange={"start": src, "duration": dur} if mat_key != "texts" else None)
        if seg.get("clip") is not None:  # audio segments have no clip
            seg["clip"] = {"scale": {"x": 1.0, "y": 1.0}, "rotation": 0.0, "rotation3d": [],
                           "transform": {"x": 0.0, "y": 0.0}, "flip": {"vertical": False, "horizontal": False},
                           "alpha": 1.0}
        if "uniform_scale" in seg:
            seg["uniform_scale"] = {"on": True, "value": 1.0}
        index = self._free_track(track_type, at, dur, params.get("track"))
        seg["render_index"] = 1 + max((s.get("render_index", 0) for _, _, s in segments(self.content)), default=-1)
        seg["track_render_index"] = index
        self.content["tracks"][index]["segments"].append(seg)
        self._apply(seg, params)
        self._touch()
        return {"segment": seg["id"], "track": index, "at": at / US,
                "duration": seg["target_timerange"]["duration"] / US}

    def _free_track(self, track_type: str, at: int, dur: int, wanted: int | None) -> int:
        tracks = self.content.setdefault("tracks", [])
        if wanted is not None:
            if not 0 <= wanted < len(tracks) or tracks[wanted].get("type") != track_type:
                raise DraftError(f"track {wanted} is not a {track_type} track; see capcut.read")
            return wanted
        for i, track in enumerate(tracks):
            if track.get("type") == track_type and not any(
                    _overlap(at, dur, s["target_timerange"]) for s in track.get("segments", [])):
                return i
        tracks.append({"id": uid(), "type": track_type, "flag": 0, "attribute": 0, "name": "",
                       "is_default_name": True, "segments": []})
        return len(tracks) - 1

    # ---------- add ----------
    def add_media(self, params: dict) -> dict:
        if not Path(params["file"]).is_absolute():  # a relative one resolves against the server's folder
            raise DraftError(f"file must be an absolute path, got {params['file']!r}")
        file = str(Path(params["file"]).resolve())
        if not Path(file).is_file():
            raise DraftError(f"file not found: {file}")
        kind = params.get("kind") or kind_of(file)
        info = self._probe(file)
        src = round(params.get("source_start", 0) * US)
        if kind == "photo":
            length = PHOTO_MATERIAL_US
            dur = round(params.get("duration", 5) * US)
        else:
            if not info.get("duration"):
                raise DraftError(f"could not read the length of {file}; is it a media file?")
            length = round(info["duration"] * US)
            if src >= length:
                raise DraftError(f"source_start {src / US}s is past the end of the file ({length / US}s)")
            dur = round(params["duration"] * US) if "duration" in params else length - src
            if src + dur > length:
                raise DraftError(f"{Path(file).name} has only {(length - src) / US}s after source_start "
                                 f"{src / US}s, asked for {dur / US}s")
        if dur <= 0:
            raise DraftError("duration must be > 0")
        tpl = self._template(kind)
        mat = tpl["mat"]
        for f in SOURCE_FIELDS:
            if f in mat:
                mat[f] = ""
        path = file.replace("\\", "/")
        local_id = self._pool_id(path)  # a file already in the media pool keeps its pool entry, as in CapCut
        if local_id is None:
            local_id = str(uuid.uuid4())
            self._pool.append({"kind": kind, "id": local_id, "path": path, "duration": length,
                               "width": info.get("width") or 0, "height": info.get("height") or 0})
        mat.update(id=uid(), path=path, duration=length, local_material_id=local_id)
        name_field = "name" if kind == "audio" else "material_name"
        mat[name_field] = Path(file).name
        if kind == "audio":
            mat.setdefault("type", "extract_music")
        else:
            mat.update(type=kind, width=info.get("width") or 0, height=info.get("height") or 0,
                       has_audio=bool(info.get("has_audio")))
        at = round(params["at"] * US)
        return self._place(tpl, "audios" if kind == "audio" else "videos", mat, at, dur, src, params,
                           "audio" if kind == "audio" else "video", lambda key: key in MEDIA_REFS)

    def add_text(self, params: dict) -> dict:
        tpl = self._template("text")
        mat = tpl["mat"]
        mat["id"] = uid()
        text = params["text"]
        body = json.loads(mat["content"])
        style = (body.get("styles") or [{}])[0]
        style["range"] = [0, utf16_len(text)]
        if "font_size" in params:
            style["size"] = params["font_size"]
            if "font_size" in mat:
                mat["font_size"] = params["font_size"]
        if "color" in params:
            rgb = _rgb(params["color"])
            style["fill"] = {"content": {"render_type": "solid", "solid": {"alpha": 1.0, "color": rgb}}}
            if "text_color" in mat:
                mat["text_color"] = params["color"]
        body.update(text=text, styles=[style])
        mat["content"] = json.dumps(body, ensure_ascii=False)
        for f in ("base_content", "recognize_text"):
            if isinstance(mat.get(f), str) and mat[f]:
                mat[f] = text
        at, dur = round(params["at"] * US), round(params.get("duration", 3) * US)
        if dur <= 0:
            raise DraftError("duration must be > 0")
        return self._place(tpl, "texts", mat, at, dur, 0, params, "text", lambda key: True)

    # ---------- edit ----------
    def _find(self, seg_id: str) -> tuple[int, dict, dict]:
        for i, track, seg in segments(self.content):
            if seg["id"] == seg_id:
                return i, track, seg
        raise DraftError(f"segment {seg_id!r} not found; see capcut.read")

    def edit(self, params: dict) -> dict:
        action, seg_id = params["action"], params["segment"]
        index, track, seg = self._find(seg_id)
        t, s = seg["target_timerange"], seg.get("source_timerange")
        speed = seg.get("speed", 1.0) or 1.0
        if action == "delete":
            track["segments"].remove(seg)
        elif action == "move":
            if "at" in params:
                t["start"] = round(params["at"] * US)
            if "track" in params and params["track"] != index:
                target = self.content["tracks"][params["track"]] if 0 <= params["track"] < len(
                    self.content["tracks"]) else None
                if target is None or target.get("type") != track.get("type"):
                    raise DraftError(f"track {params['track']} is not a {track.get('type')} track")
                track["segments"].remove(seg)
                target["segments"].append(seg)
                seg["track_render_index"] = params["track"]
        elif action == "trim":
            if "at" in params:
                t["start"] = round(params["at"] * US)
            if "source_start" in params:
                if s is None:
                    raise DraftError("this segment has no source range (text)")
                s["start"] = round(params["source_start"] * US)
            if "duration" in params:
                t["duration"] = round(params["duration"] * US)
                if s is not None:
                    s["duration"] = round(t["duration"] * speed)
        elif action == "split":
            cut = round(params["at"] * US)
            if not t["start"] < cut < t["start"] + t["duration"]:
                raise DraftError("split point must be inside the segment")
            right = copy.deepcopy(seg)
            right["id"] = uid()
            right["extra_material_refs"] = []
            for ref_id in list(seg.get("extra_material_refs", [])):  # each half owns its extra materials
                key, ref = find_material(self.content, ref_id)
                if ref is None:
                    continue
                if key == "transitions":  # a transition sits at the clip's end: it moves to the right half
                    seg["extra_material_refs"].remove(ref_id)
                    right["extra_material_refs"].append(ref_id)
                    continue
                clone = copy.deepcopy(ref)
                clone["id"] = uid()
                self.content["materials"][key].append(clone)
                right["extra_material_refs"].append(clone["id"])
            left = cut - t["start"]
            right["target_timerange"] = {"start": cut, "duration": t["duration"] - left}
            t["duration"] = left
            if s is not None:
                used = round(left * speed)
                right["source_timerange"] = {"start": s["start"] + used, "duration": s["duration"] - used}
                s["duration"] = used
            right["render_index"] = 1 + max(x.get("render_index", 0) for _, _, x in segments(self.content))
            track["segments"].append(right)
            self._touch()
            return {"left": seg_id, "right": right["id"]}
        elif action == "set":
            self._apply(seg, params)
        self._touch()
        return {"segment": seg_id, "action": action}

    def _apply(self, seg: dict, p: dict) -> None:
        clip = seg.get("clip")
        if clip is None and any(k in p for k in ("scale", "pos_x", "pos_y", "rotation", "opacity")):
            raise DraftError("audio has no picture: scale, position, rotation and opacity do not apply")
        if "scale" in p:
            clip["scale"] = {"x": p["scale"], "y": p["scale"]}
            if "uniform_scale" in seg:
                seg["uniform_scale"]["value"] = p["scale"]
        for key, (outer, inner) in {"pos_x": ("transform", "x"), "pos_y": ("transform", "y")}.items():
            if key in p:
                clip[outer][inner] = p[key]
        if "rotation" in p:
            clip["rotation"] = float(p["rotation"])
        if "opacity" in p:
            clip["alpha"] = p["opacity"]
        if "volume" in p:
            seg["volume"] = p["volume"]
        if "visible" in p:
            seg["visible"] = p["visible"]
        if "speed" in p:
            src = seg.get("source_timerange")
            if src is None:
                raise DraftError("speed applies to video and audio clips")
            seg["speed"] = float(p["speed"])
            seg["target_timerange"]["duration"] = round(src["duration"] / p["speed"])
            for ref_id in seg.get("extra_material_refs", []):
                key, ref = find_material(self.content, ref_id)
                if key == "speeds":
                    ref["speed"] = float(p["speed"])

    # ---------- effects ----------
    def library(self) -> list[dict]:
        """Transitions, filters, video effects and animations found in this and other drafts, one per resource."""
        seen, items = set(), []
        sources = [self.content]
        for folder in self._others():
            try:
                sources.append(read_json(main_timeline(folder)))
            except (DraftError, OSError, ValueError):
                continue
        for content in sources:
            for item in _effects_of(content):
                key = (item["kind"], item["resource_id"])
                if key not in seen:
                    seen.add(key)
                    items.append(item)
        return items

    def apply_effect(self, params: dict) -> dict:
        kind, name = params["kind"], params["name"].lower()
        found = [i for i in self.library() if i["kind"] == kind and name in (i["name"].lower(), i["resource_id"])]
        if not found:
            raise DraftError(f"no {kind} named {params['name']!r}: apply it once by hand in any CapCut draft, "
                             "then see capcut.effects")
        item = copy.deepcopy(found[0]["data"])
        _, track, seg = self._find(params["segment"])
        refs = seg.setdefault("extra_material_refs", [])
        mats = self.content["materials"]
        seg_dur = seg["target_timerange"]["duration"]
        if kind == "animation":
            mat_key, _ = find_material(self.content, seg.get("material_id"))
            target = found[0].get("target")
            if (target == "sticker") != (mat_key == "texts") and target in ("sticker", "video"):
                raise DraftError(f"{found[0]['name']!r} is a {'text' if target == 'sticker' else 'video'} animation")
            holder = next((m for r in refs for k, m in [find_material(self.content, r)]
                           if k == "material_animations"), None)
            if holder is None:
                holder = {"id": uid(), "type": "sticker_animation", "animations": [], "multi_language_current": "none"}
                mats.setdefault("material_animations", []).append(holder)
                refs.append(holder["id"])
            dur = min(round(params["duration"] * US) if "duration" in params else item["duration"], seg_dur)
            item.update(duration=dur, start=seg_dur - dur if item["type"] == "out" else 0)
            holder["animations"] = [a for a in holder.get("animations", []) if a.get("type") != item["type"]] + [item]
        else:
            key = {"transition": "transitions", "filter": "effects", "effect": "video_effects"}[kind]
            if kind in ("transition", "filter"):  # one per clip: replace the old one
                for r in list(refs):
                    k, m = find_material(self.content, r)
                    if k == key and (kind == "transition" or m.get("type") == "filter"):
                        refs.remove(r)
                        mats[k].remove(m)
            item["id"] = uid()
            if kind == "transition":
                if "duration" in params:
                    item["duration"] = round(params["duration"] * US)
                end = seg["target_timerange"]["start"] + seg_dur
                if not any(o["target_timerange"]["start"] == end for o in track["segments"]):
                    raise DraftError("a transition goes between two clips: no clip starts where this one ends")
            mats.setdefault(key, []).append(item)
            refs.append(item["id"])
        self._touch()
        return {"segment": seg["id"], "kind": kind, "name": found[0]["name"], "cached": found[0]["cached"]}

    def raw_patch(self, patch: dict) -> dict:
        _merge(self.content, patch)
        self._touch()
        return {"ok": True}

    def _touch(self) -> None:
        # CapCut lays the main track out in list order, not by start time: keep lists in time order
        for track in self.content.get("tracks", []):
            track.get("segments", []).sort(key=lambda s: s["target_timerange"]["start"])
        self.content["duration"] = max((s["target_timerange"]["start"] + s["target_timerange"]["duration"]
                                        for _, _, s in segments(self.content)), default=0)
        self.dirty = True

    # ---------- check ----------
    def validate(self) -> dict:
        c, issues = self.content, []
        ids: dict[str, dict] = {}
        for key, items in c.get("materials", {}).items():
            for m in items if isinstance(items, list) else []:
                if isinstance(m, dict) and "id" in m:
                    # CapCut itself writes a material shared by split halves twice, identical: that is fine
                    if m["id"] in ids and ids[m["id"]] != m:
                        issues.append(f"duplicate material id {m['id']} ({key})")
                    ids[m["id"]] = m
                    path = m.get("path")
                    if key in ("videos", "audios") and path and not Path(path).exists():
                        issues.append(f"missing media file: {path}")
        for i, track, seg in segments(c):
            t = seg["target_timerange"]
            if not all(isinstance(t.get(k), int) and t[k] >= 0 for k in ("start", "duration")) or not t["duration"]:
                issues.append(f"segment {seg['id']}: bad time range {t}")
            if seg.get("material_id") not in ids:
                issues.append(f"segment {seg['id']}: material {seg.get('material_id')} missing")
            missing = [r for r in seg.get("extra_material_refs", []) if r not in ids]
            if missing:
                issues.append(f"segment {seg['id']}: extra materials missing {missing}")
            key, m = find_material(c, seg.get("material_id"))
            s = seg.get("source_timerange")
            if m and s and key in ("videos", "audios") and s["start"] + s["duration"] > m.get("duration", math.inf):
                issues.append(f"segment {seg['id']}: uses {(s['start'] + s['duration']) / US}s of a "
                              f"{m['duration'] / US}s file")
        for i, track in enumerate(c.get("tracks", [])):
            segs = sorted(track.get("segments", []), key=lambda x: x["target_timerange"]["start"])
            for a, b in zip(segs, segs[1:]):
                if _overlap(b["target_timerange"]["start"], b["target_timerange"]["duration"], a["target_timerange"]):
                    issues.append(f"track {i}: segments {a['id']} and {b['id']} overlap")
        # magnetic main track (the first video track, CapCut's default): CapCut closes its gaps on open and moves
        # the clips after them left, while text and overlay tracks stay put
        main = next((t for t in c.get("tracks", []) if t.get("type") == "video"), None)
        if main and (c.get("config") or {}).get("maintrack_adsorb", True):
            end = 0
            for seg in sorted(main.get("segments", []), key=lambda x: x["target_timerange"]["start"]):
                t = seg["target_timerange"]
                if t["start"] - end > 1000:  # under 1 ms is rounding, not a gap
                    issues.append(f"main track: gap {end / US}-{t['start'] / US}s; CapCut closes it on open and "
                                  "moves later clips left: move them to close it, or turn the magnet off in CapCut")
                end = max(end, t["start"] + t["duration"])
        return {"ok": not issues, "issues": issues}

    # ---------- save ----------
    def save(self) -> dict:
        """Back up every file we touch, then write the main timeline and its mirrors."""
        targets = [self.path] + [p for p in (self.folder / "draft_content.json", self.folder / "template-2.tmp",
                                             self.path.parent / "template-2.tmp") if p.exists() and p != self.path]
        backup = self.folder / ".dccmcp_backup" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup.mkdir(parents=True)
        extra = [p for p in (self.meta_path, self.folder / "draft_virtual_store.json") if p.exists()]
        for p in targets + extra:
            dst = backup / p.relative_to(self.folder)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
        self.content["update_time"] = int(time.time() * US)
        for p in targets:
            write_json(p, self.content)
        if self.meta is not None:
            self._write_meta()
        self.dirty, self._pool = False, []
        return {"written": [str(p) for p in targets], "backup": str(backup)}

    def _write_meta(self) -> None:
        m = self.meta
        m["tm_duration"] = self.content.get("duration", 0)
        m["tm_draft_modified"] = int(time.time() * US)
        groups = m.setdefault("draft_materials", [])
        pool = next((g for g in groups if g.get("type") == 0), None)
        if pool is None:
            pool = {"type": 0, "value": []}
            groups.insert(0, pool)
        now = int(time.time())
        for e in self._pool:
            pool["value"].append({
                "ai_group_type": "", "create_time": now, "duration": e["duration"], "enter_from": 0,
                "extra_info": Path(e["path"]).name, "file_Path": e["path"], "height": e["height"], "id": e["id"],
                "import_time": now, "import_time_ms": now * 1000 * 1000, "item_source": 1, "material_color_tag": "",
                "md5": "", "metetype": POOL_TYPE[e["kind"]],
                "roughcut_time_range": {"duration": e["duration"], "start": 0},
                "sub_time_range": {"duration": -1, "start": -1}, "type": 0, "width": e["width"]})
        write_json(self.meta_path, m)
        store_path = self.folder / "draft_virtual_store.json"
        if self._pool and store_path.exists():  # the media panel lists pool items from here (type 1)
            store = read_json(store_path)
            groups = store.setdefault("draft_virtual_store", [])
            links = next((g for g in groups if g.get("type") == 1), None)
            if links is None:
                links = {"type": 1, "value": []}
                groups.append(links)
            links["value"] += [{"child_id": e["id"], "parent_id": ""} for e in self._pool]
            write_json(store_path, store)

    def _pool_id(self, path: str) -> str | None:
        """local_material_id of a pool entry for this file (saved or added in this session)."""
        key = path.lower()
        pending = [(e["path"], e["id"]) for e in self._pool]
        saved = [(e.get("file_Path", ""), e.get("id")) for g in (self.meta or {}).get("draft_materials", [])
                 if g.get("type") == 0 for e in g.get("value", [])]
        return next((i for p, i in pending + saved if p.replace("\\", "/").lower() == key and i), None)


def _harvest(content: dict, kind: str) -> dict | None:
    """kind: video | photo | audio | text, matched by the material's type."""
    for _, track, seg in segments(content):
        key, mat = find_material(content, seg.get("material_id"))
        if mat is None:
            continue
        mtype = mat.get("type")
        ok = {"video": key == "videos" and mtype == "video", "photo": key == "videos" and mtype == "photo",
              "audio": key == "audios", "text": key == "texts" and mtype == "text"}[kind]
        if ok:
            refs = []
            for ref_id in seg.get("extra_material_refs", []):
                rkey, ref = find_material(content, ref_id)
                if ref is not None:
                    refs.append((rkey, ref))
            return copy.deepcopy({"seg": seg, "mat": mat, "refs": refs})
    return None


def _effects_of(content: dict):
    mats = content.get("materials", {})
    groups = [("transition", m) for m in mats.get("transitions", [])]
    groups += [("filter", m) for m in mats.get("effects", []) if m.get("type") == "filter"]
    groups += [("effect", m) for m in mats.get("video_effects", [])]
    groups += [("animation", a) for m in mats.get("material_animations", []) for a in m.get("animations", [])]
    for kind, data in groups:
        rid = str(data.get("resource_id") or data.get("effect_id") or "")
        if not rid:
            continue  # not a CapCut catalogue resource
        item = {"kind": kind, "name": data.get("name", ""), "resource_id": rid,
                "cached": bool(data.get("path")) and Path(data["path"]).exists(), "data": data}
        if kind == "animation":
            item.update(type=data.get("type"), target=data.get("material_type"))
        yield item


def _effect_names(content: dict, seg: dict) -> list[str]:
    """'transition: Polkadot Slide', 'animation in: Neon Typing 2'... on this segment, as capcut.effects names them."""
    kinds = {"transitions": "transition", "video_effects": "effect", "effects": "filter"}
    names = []
    for ref in seg.get("extra_material_refs", []):
        key, m = find_material(content, ref)
        if key in kinds and (key != "effects" or m.get("type") == "filter"):
            names.append(f"{kinds[key]}: {m.get('name', '')}")
        elif key == "material_animations":
            names += [f"animation {a.get('type')}: {a.get('name', '')}" for a in m.get("animations", [])]
    return names


def _overlap(at: int, dur: int, other: dict) -> bool:
    return at < other["start"] + other["duration"] and other["start"] < at + dur


def _text_of(mat: dict) -> str | None:
    try:
        return json.loads(mat.get("content", "")).get("text")
    except ValueError:
        return None


def _rgb(hex_color: str) -> list[float]:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise DraftError(f"color must look like #RRGGBB, got {hex_color!r}")
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def _merge(target: dict, patch: dict) -> None:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(target.get(k), dict):
            _merge(target[k], v)
        else:
            target[k] = v
