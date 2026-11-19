"""capcut plugin without CapCut: a draft folder in the 9.8 layout, ffprobe and the process check stubbed."""
import json
from pathlib import Path

import pytest

from dcc_mcp.assets import AssetStore
from dcc_mcp.registry import Registry
from dcc_mcp.runner import Runner
from plugins.capcut import register
from plugins.capcut.backend import CapCutBackend
from plugins.capcut.draft import find_material

US = 1_000_000
MAIN = "11A3D371-8B40-4e59-AAA2-AD61128045C9"


def seg(sid, mid, refs, start, dur, src=0):
    return {"id": sid, "material_id": mid, "extra_material_refs": refs, "speed": 1.0, "volume": 1.0,
            "visible": True, "render_index": 0, "track_render_index": 0, "keyframe_refs": [],
            "target_timerange": {"start": start, "duration": dur},
            "source_timerange": None if src is None else {"start": src, "duration": dur},
            "clip": {"scale": {"x": 1.0, "y": 1.0}, "rotation": 0.0, "rotation3d": [], "transform": {"x": 0.0, "y": 0.0},
                     "flip": {"vertical": False, "horizontal": False}, "alpha": 1.0},
            "uniform_scale": {"on": True, "value": 1.0}}


def make_draft(root: Path, name: str, media: Path, with_text=True) -> Path:
    folder = root / name
    content = {
        "id": MAIN, "duration": 3 * US, "fps": 30.0, "canvas_config": {"width": 1080, "height": 1920},
        "platform": {"app_version": "9.8.0", "app_source": "cc"},
        "materials": {
            "videos": [{"id": "V1", "type": "video", "path": media.as_posix(), "duration": 2 * US,
                        "material_name": media.name, "local_material_id": "old", "unique_id": "abc",
                        "width": 480, "height": 854, "has_audio": True}],
            "speeds": [{"id": "S1", "type": "speed", "speed": 1.0}],
            "transitions": [{"id": "X1", "type": "transition"}],
            "texts": [{"id": "T1", "type": "text", "font_size": 15.0, "text_color": "#FFFFFF",
                       "content": json.dumps({"text": "old", "styles": [{"range": [0, 3], "size": 15.0, "font": {"path": "f.ttf"}}]})}],
            "material_animations": [{"id": "A1", "type": "sticker_animation"}],
            "audios": [{"id": "AU1", "type": "extract_music", "name": "a.mp3", "path": media.as_posix(),
                        "duration": 2 * US, "music_id": "m"}],
        },
        "tracks": [{"id": "TR1", "type": "video", "segments": [seg("G1", "V1", ["S1", "X1"], 0, 2 * US)]},
                   {"id": "TR2", "type": "audio", "segments": [{**seg("G3", "AU1", [], 0, 2 * US), "clip": None}]}],
    }
    if with_text:
        content["tracks"].append({"id": "TR3", "type": "text", "segments": [seg("G2", "T1", ["A1"], 0, 3 * US, src=None)]})
    else:
        del content["materials"]["texts"]
    (folder / "Timelines" / MAIN).mkdir(parents=True)
    (folder / "Timelines" / "project.json").write_text(json.dumps({"main_timeline_id": MAIN}), encoding="utf-8")
    for p in ("draft_content.json", "template-2.tmp", f"Timelines/{MAIN}/draft_content.json",
              f"Timelines/{MAIN}/template-2.tmp"):
        (folder / p).write_text(json.dumps(content), encoding="utf-8")
    meta = {"tm_duration": 2 * US, "draft_materials": [{"type": 0, "value": []}, {"type": 1, "value": []}]}
    (folder / "draft_meta_info.json").write_text(json.dumps(meta), encoding="utf-8")
    store = {"draft_virtual_store": [{"type": 1, "value": []}]}
    (folder / "draft_virtual_store.json").write_text(json.dumps(store), encoding="utf-8")
    return folder


@pytest.fixture
def env(tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"x")
    (tmp_path / "pic.png").write_bytes(b"x")
    drafts = tmp_path / "drafts"
    make_draft(drafts, "one", media)
    probe = {"clip.mp4": {"duration": 7.0, "width": 640, "height": 360, "has_audio": True},
             "pic.png": {"duration": 0.04, "width": 800, "height": 600, "has_audio": False}}
    state = {"running": False}
    reg = Registry()
    register(reg, {"drafts_dir": str(drafts), "allow_raw": True})
    backend = CapCutBackend({"drafts_dir": str(drafts)}, probe=lambda p: probe[Path(p).name],
                            running=lambda: state["running"])
    reg.backends["capcut"] = lambda: backend  # one instance, so tests can look inside its drafts
    runner = Runner(reg, AssetStore(tmp_path / "work"))
    run = lambda key, **params: runner.run_op(key, None, params)  # noqa: E731
    env.backend = backend
    return run, drafts / "one", tmp_path, state


def nested(folder):
    return json.loads((folder / "Timelines" / MAIN / "draft_content.json").read_text(encoding="utf-8"))


def test_add_video_uses_file_length_and_free_track(env):
    run, folder, tmp, _ = env
    r = run("capcut.add", draft="one", file=str(tmp / "clip.mp4"), at=1)
    assert r["status"] == "ok", r
    assert r["metrics"]["track"] == 3  # track 0 is busy at 1s: a new video track, not an overlap
    assert r["metrics"]["duration"] == 7.0
    tl = run("capcut.read", draft="one")["metrics"]
    assert tl["unsaved_edits"] and tl["duration"] == 8.0


def test_add_media_fresh_ids_and_no_template_effects(env):
    run, folder, tmp, _ = env
    sid = run("capcut.add", draft="one", file=str(tmp / "clip.mp4"), at=2, track=0)["metrics"]["segment"]
    draft = _draft(run, folder)
    s = next(x for t in draft.content["tracks"] for x in t["segments"] if x["id"] == sid)
    _, mat = find_material(draft.content, s["material_id"])
    assert mat["duration"] == 7 * US and mat["width"] == 640 and mat["unique_id"] == ""
    assert mat["local_material_id"] not in ("", "old")
    kinds = [find_material(draft.content, r)[0] for r in s["extra_material_refs"]]
    assert kinds == ["speeds"]  # the template's transition is not copied


def _draft(run, folder):
    return env.backend.draft(folder.name)


def test_image_gets_default_duration(env):
    run, folder, tmp, _ = env
    r = run("capcut.add", draft="one", file=str(tmp / "pic.png"), at=0)
    assert r["status"] == "ok", r
    assert r["metrics"]["duration"] == 5.0


def test_text_style_range_and_color(env):
    run, folder, tmp, _ = env
    r = run("capcut.text", draft="one", text="Привет 👋", at=0.5, color="#FF0000", font_size=20)
    assert r["status"] == "ok", r
    draft = _draft(run, folder)
    mat = draft.content["materials"]["texts"][-1]
    body = json.loads(mat["content"])
    assert body["text"] == "Привет 👋" and body["styles"][0]["range"] == [0, 9]  # emoji = 2 UTF-16 units
    assert body["styles"][0]["font"] == {"path": "f.ttf"} and body["styles"][0]["size"] == 20
    assert mat["text_color"] == "#FF0000"


def test_text_template_from_another_draft(env):
    run, folder, tmp, _ = env
    make_draft(folder.parent, "bare", tmp / "clip.mp4", with_text=False)
    assert run("capcut.text", draft="bare", text="hi", at=0)["status"] == "ok"


def test_split_and_speed_keep_source_in_step(env):
    run, folder, tmp, _ = env
    sid = run("capcut.add", draft="one", file=str(tmp / "clip.mp4"), at=2)["metrics"]["segment"]
    run("capcut.edit", draft="one", segment=sid, action="set", speed=2.0)
    r = run("capcut.edit", draft="one", segment=sid, action="split", at=3)
    assert r["status"] == "ok", r
    draft = _draft(run, folder)
    segs = {s["id"]: s for t in draft.content["tracks"] for s in t["segments"]}
    left, right = segs[sid], segs[r["metrics"]["right"]]
    assert left["target_timerange"] == {"start": 2 * US, "duration": 1 * US}
    assert left["source_timerange"] == {"start": 0, "duration": 2 * US}
    assert right["target_timerange"] == {"start": 3 * US, "duration": int(2.5 * US)}
    assert right["source_timerange"] == {"start": 2 * US, "duration": 5 * US}
    assert set(left["extra_material_refs"]).isdisjoint(right["extra_material_refs"])
    assert run("capcut.validate", draft="one")["status"] == "ok"


def test_save_writes_main_timeline_mirrors_meta_and_backup(env):
    run, folder, tmp, _ = env
    run("capcut.add", draft="one", file=str(tmp / "clip.mp4"), at=2, track=0)
    r = run("capcut.save", draft="one")
    assert r["status"] == "ok", r
    main = nested(folder)
    assert len(main["tracks"][0]["segments"]) == 2
    for p in ("draft_content.json", "template-2.tmp", f"Timelines/{MAIN}/template-2.tmp"):
        assert json.loads((folder / p).read_text(encoding="utf-8")) == main
    meta = json.loads((folder / "draft_meta_info.json").read_text(encoding="utf-8"))
    assert meta["tm_duration"] == 9 * US
    pool = meta["draft_materials"][0]["value"]
    assert pool[-1]["metetype"] == "video" and pool[-1]["id"] == main["materials"]["videos"][-1]["local_material_id"]
    backups = list((folder / ".dccmcp_backup").iterdir())
    assert len(backups) == 1 and (backups[0] / "Timelines" / MAIN / "draft_content.json").exists()
    assert not run("capcut.read", draft="one")["metrics"]["unsaved_edits"]


def test_save_refuses_open_draft_running_capcut_and_invalid(env):
    run, folder, tmp, state = env
    before = nested(folder)
    run("capcut.add", draft="one", file=str(tmp / "clip.mp4"), at=0, track=0)  # overlaps G1
    (folder / ".locked").write_text("")
    assert "open in CapCut" in run("capcut.save", draft="one", force=True)["notes"]
    (folder / ".locked").unlink()
    state["running"] = True
    assert "running" in run("capcut.save", draft="one")["notes"]
    state["running"] = False
    r = run("capcut.save", draft="one")
    assert r["status"] == "fail" and "overlap" in r["notes"]
    assert nested(folder) == before


def test_draft_name_cannot_leave_drafts_folder(env):
    run, *_ = env
    r = run("capcut.read", draft="..")
    assert r["status"] == "fail" and "no draft" in r["notes"]


def test_encrypted_draft_is_reported(env):
    run, folder, *_ = env
    (folder / "Timelines" / MAIN / "draft_content.json").write_bytes(b"\x89binary")
    assert "not plain JSON" in run("capcut.read", draft="one")["notes"]


def test_list_and_discard(env):
    run, folder, tmp, _ = env
    run("capcut.add", draft="one", file=str(tmp / "clip.mp4"), at=5)
    drafts = run("capcut.list")["metrics"]["drafts"]
    assert drafts[0]["name"] == "one" and drafts[0]["unsaved_edits"] and drafts[0]["app_version"] == "9.8.0"
    assert run("capcut.discard", draft="one")["metrics"]["discarded"]
    assert run("capcut.read", draft="one")["metrics"]["duration"] == 3.0


def test_same_file_shares_one_pool_entry_and_is_registered(env):
    run, folder, tmp, _ = env
    run("capcut.add", draft="one", file=str(tmp / "clip.mp4"), at=2)  # 7 s clips end to end on the main track
    run("capcut.add", draft="one", file=str(tmp / "clip.mp4"), at=9)
    assert run("capcut.save", draft="one")["status"] == "ok"
    vids = nested(folder)["materials"]["videos"][1:]
    assert len({v["local_material_id"] for v in vids}) == 1
    pool = json.loads((folder / "draft_meta_info.json").read_text(encoding="utf-8"))["draft_materials"][0]["value"]
    store = json.loads((folder / "draft_virtual_store.json").read_text(encoding="utf-8"))["draft_virtual_store"][0]
    assert [e["id"] for e in pool] == [vids[0]["local_material_id"]] == [e["child_id"] for e in store["value"]]
    # a later session finds the saved pool entry instead of adding another
    assert run("capcut.add", draft="one", file=str(tmp / "clip.mp4"), at=16)["status"] == "ok"
    assert run("capcut.save", draft="one")["status"] == "ok"
    assert len(json.loads((folder / "draft_meta_info.json").read_text(encoding="utf-8"))["draft_materials"][0]["value"]) == 1


def test_audio_clip_has_no_picture(env):
    run, folder, tmp, _ = env
    backend = globals()["env"].backend
    (tmp / "a.wav").write_bytes(b"x")
    backend.probe = lambda p: {"duration": 1.5, "has_audio": True}
    backend.open.clear()
    r = run("capcut.add", draft="one", file=str(tmp / "a.wav"), at=3, volume=0.5)
    assert r["status"] == "ok", r
    seg = next(s for t in _draft(run, folder).content["tracks"] for s in t["segments"] if s["id"] == r["metrics"]["segment"])
    assert seg["clip"] is None and seg["volume"] == 0.5
    r = run("capcut.edit", draft="one", segment=seg["id"], action="set", scale=2)
    assert r["status"] == "fail" and "no picture" in r["notes"]


def add_effects(folder: Path) -> None:
    """Effects as CapCut 9.8 stores them (2026-11-18): refs on the clip, transition on the clip before the cut."""
    for p in ("draft_content.json", f"Timelines/{MAIN}/draft_content.json"):
        c = json.loads((folder / p).read_text(encoding="utf-8"))
        m = c["materials"]
        m["transitions"] = [{"id": "TRX", "type": "transition", "name": "Polkadot Slide", "resource_id": "111",
                             "duration": 533333, "is_overlap": True, "path": "x"}]
        m["effects"] = [{"id": "FLT", "type": "filter", "name": "Rainy Neon", "resource_id": "222", "path": "x"}]
        m["video_effects"] = [{"id": "VFX", "type": "video_effect", "name": "Glowing Heart", "resource_id": "333"}]
        m["material_animations"][0]["animations"] = [{"id": "444", "type": "in", "start": 0, "duration": 500000,
                                                      "name": "Neon Typing 2", "resource_id": "444",
                                                      "material_type": "sticker"}]
        (folder / p).write_text(json.dumps(c), encoding="utf-8")


def test_effects_from_another_draft(env):
    run, folder, tmp, _ = env
    other = make_draft(folder.parent, "fx", tmp / "clip.mp4")
    add_effects(other)
    fx = run("capcut.effects", draft="one")["metrics"]
    assert [e["name"] for e in fx["transitions"]] == ["Polkadot Slide"] and fx["animations"][0]["for"] == "text"
    clip2 = run("capcut.add", draft="one", file=str(tmp / "clip.mp4"), at=2, track=0)["metrics"]["segment"]
    ok = lambda **p: run("capcut.apply", draft="one", **p)  # noqa: E731
    assert ok(segment="G1", kind="transition", name="polkadot slide", duration=0.3)["status"] == "ok"
    assert ok(segment="G1", kind="transition", name="Polkadot Slide")["status"] == "ok"  # replaces, not adds
    assert ok(segment=clip2, kind="filter", name="Rainy Neon")["status"] == "ok"
    assert ok(segment=clip2, kind="effect", name="333")["status"] == "ok"
    assert ok(segment="G2", kind="animation", name="Neon Typing 2", duration=1)["status"] == "ok"
    bad = ok(segment=clip2, kind="transition", name="Polkadot Slide")
    assert bad["status"] == "fail" and "between two clips" in bad["notes"]
    assert "text animation" in ok(segment=clip2, kind="animation", name="Neon Typing 2")["notes"]
    d = _draft(run, folder).content
    refs = {s["id"]: s["extra_material_refs"] for t in d["tracks"] for s in t["segments"]}
    kinds = lambda sid: sorted(find_material(d, r)[0] for r in refs[sid])  # noqa: E731
    assert kinds("G1").count("transitions") == 1 and len(d["materials"]["transitions"]) == 1
    assert {"effects", "video_effects"} <= set(kinds(clip2))
    anim = next(find_material(d, r)[1] for r in refs["G2"] if find_material(d, r)[0] == "material_animations")
    assert anim["animations"][0]["duration"] == 1 * US
    assert run("capcut.save", draft="one")["status"] == "ok"


def test_saved_segments_are_in_time_order(env):
    # CapCut lays the main track out in list order, not by start time (seen on 9.8, 2026-11-18)
    run, folder, tmp, _ = env
    run("capcut.add", draft="one", file=str(tmp / "clip.mp4"), at=3, duration=1, track=0)
    run("capcut.edit", draft="one", segment="G1", action="split", at=1)  # right half 1..2
    run("capcut.add", draft="one", file=str(tmp / "clip.mp4"), at=2, duration=1, track=0)  # between 2 and 3
    last = run("capcut.add", draft="one", file=str(tmp / "clip.mp4"), at=8, duration=1, track=0)["metrics"]["segment"]
    run("capcut.edit", draft="one", segment=last, action="move", at=4)
    assert run("capcut.save", draft="one")["status"] == "ok"
    for track in nested(folder)["tracks"]:
        starts = [s["target_timerange"]["start"] for s in track["segments"]]
        assert starts == sorted(starts), track["id"]
    read = run("capcut.read", draft="one")["metrics"]["tracks"][0]["segments"]
    assert [s["at"] for s in read] == [0, 1, 2, 3, 4]


def test_split_moves_transition_to_right_half(env):
    run, folder, tmp, _ = env
    add_effects(folder)
    run("capcut.add", draft="one", file=str(tmp / "clip.mp4"), at=2, track=0)
    run("capcut.apply", draft="one", segment="G1", kind="transition", name="Polkadot Slide")
    right = run("capcut.edit", draft="one", segment="G1", action="split", at=1)["metrics"]["right"]
    d = _draft(run, folder).content
    refs = {s["id"]: s["extra_material_refs"] for t in d["tracks"] for s in t["segments"]}
    has_trx = lambda sid: any(find_material(d, r)[0] == "transitions" for r in refs[sid])  # noqa: E731
    assert not has_trx("G1") and has_trx(right)


def test_read_shows_file_volume_place_and_effects(env):
    run, folder, tmp, _ = env
    add_effects(folder)
    clip2 = run("capcut.add", draft="one", file=str(tmp / "clip.mp4"), at=2, duration=1, track=0,
                volume=0.3, pos_y=-0.5)["metrics"]["segment"]
    run("capcut.apply", draft="one", segment="G1", kind="transition", name="Polkadot Slide")
    run("capcut.apply", draft="one", segment=clip2, kind="filter", name="Rainy Neon")
    run("capcut.apply", draft="one", segment="G2", kind="animation", name="Neon Typing 2")
    segs = {s["id"]: s for t in run("capcut.read", draft="one")["metrics"]["tracks"] for s in t["segments"]}
    assert segs[clip2]["file"] == (tmp / "clip.mp4").resolve().as_posix()
    assert segs[clip2]["volume"] == 0.3 and segs[clip2]["pos_y"] == -0.5 and segs[clip2]["scale"] == 1.0
    assert segs[clip2]["effects"] == ["filter: Rainy Neon"]
    assert segs["G1"]["effects"] == ["transition: Polkadot Slide"]
    assert segs["G2"]["effects"] == ["animation in: Neon Typing 2"] and "volume" not in segs["G2"]
    assert "file" not in segs["G2"]  # text has no media file


def test_add_refuses_relative_path_and_too_long_clip(env):
    run, folder, tmp, _ = env
    r = run("capcut.add", draft="one", file="clip.mp4", at=5)
    assert r["status"] == "fail" and "absolute path" in r["notes"]
    r = run("capcut.add", draft="one", file=str(tmp / "clip.mp4"), at=5, source_start=6, duration=2)
    assert r["status"] == "fail" and "1.0s" in r["notes"]  # 7 s file: only 1 s left after 6 s
    assert not run("capcut.read", draft="one")["metrics"]["unsaved_edits"]


def test_save_without_edits_writes_nothing(env):
    run, folder, tmp, _ = env
    before = nested(folder)
    r = run("capcut.save", draft="one")
    assert r["status"] == "warn" and "nothing written" in r["notes"]
    assert nested(folder) == before and not (folder / ".dccmcp_backup").exists()


def test_validate_reports_gap_on_magnetic_main_track(env):
    # CapCut 9.8 closes gaps on the main track when it opens a draft (seen 2026-11-18), titles stay put
    run, folder, tmp, _ = env
    run("capcut.add", draft="one", file=str(tmp / "clip.mp4"), at=3, duration=1, track=0)  # G1 ends at 2 s
    r = run("capcut.validate", draft="one")
    assert r["status"] == "fail" and "main track: gap 2.0-3.0s" in r["notes"]
    assert run("capcut.save", draft="one")["status"] == "fail"
    run("capcut.add", draft="one", file=str(tmp / "clip.mp4"), at=0, duration=1)  # overlay track: gaps are fine
    run("capcut.raw", draft="one", patch={"config": {"maintrack_adsorb": False}})  # magnet off in CapCut
    assert run("capcut.validate", draft="one")["status"] == "ok"


def test_read_photo_has_no_volume(env):
    run, folder, tmp, _ = env
    pic = run("capcut.add", draft="one", file=str(tmp / "pic.png"), at=2, duration=1, track=0)["metrics"]["segment"]
    seg = next(s for t in run("capcut.read", draft="one")["metrics"]["tracks"] for s in t["segments"] if s["id"] == pic)
    assert seg["kind"] == "photo" and "volume" not in seg and seg["file"].endswith("pic.png")
