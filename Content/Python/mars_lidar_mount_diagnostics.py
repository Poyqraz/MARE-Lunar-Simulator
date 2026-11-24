"""Observe the live PIE LiDAR mount relative to base_link; never command motion.

Samples run on the editor's Slate post-tick, not at the LiDAR capture request
or GPU render. Matching simulation stamps alone does not make them simultaneous.
"""

import builtins
import json
import math
from pathlib import Path
import time
from urllib.request import urlopen
import uuid

import mars_sensor_setup as frames

_KEY = "_mars_lidar_mount_observer"


def _get_snapshot():
    with urlopen("http://127.0.0.1:8766/mission/snapshot", timeout=3) as response:
        return json.load(response)


def _matrix(value):
    if (not isinstance(value, list) or len(value) != 4
            or any(not isinstance(row, list) or len(row) != 4 for row in value)
            or any(type(x) not in (int, float) or not math.isfinite(x) for row in value for x in row)):
        raise ValueError("Sensor config must contain a finite 4x4 LiDAR transform")
    if any(abs(value[3][i] - (1 if i == 3 else 0)) > 1e-8 for i in range(4)):
        raise ValueError("Invalid LiDAR transform last row")
    for i in range(3):
        for j in range(3):
            dot = sum(value[k][i] * value[k][j] for k in range(3))
            if abs(dot - (1 if i == j else 0)) > 1e-5:
                raise ValueError("LiDAR transform is not orthonormal")
    a, b, c = ([value[i][j] for i in range(3)] for j in range(3))
    det = sum(a[i] * (b[(i + 1) % 3] * c[(i + 2) % 3] - b[(i + 2) % 3] * c[(i + 1) % 3])
              for i in range(3))
    if abs(det - 1.0) > 1e-5:
        raise ValueError("LiDAR transform is not right-handed")
    return value


def _difference(reference, observed):
    distance = math.sqrt(sum((reference[i][3] - observed[i][3]) ** 2 for i in range(3)))
    trace = sum(reference[k][i] * observed[k][i] for i in range(3) for k in range(3))
    angle = math.degrees(math.acos(max(-1.0, min(1.0, (trace - 1.0) / 2.0))))
    return distance, angle


def _components(unreal):
    worlds = unreal.EditorLevelLibrary.get_pie_worlds(False)
    if len(worlds) != 1:
        raise ValueError("Start exactly one local Unreal Play session")
    world = worlds[0]
    pawns = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Pawn)
    rovers = [p for p in pawns if p.get_class().get_name().startswith("Leo_Raph")]
    if len(rovers) != 1:
        raise ValueError("Expected exactly one Leo_Raph rover in Play")
    rover = rovers[0]
    lidars = rover.get_components_by_class(unreal.UnrealLidarCam)
    if len(lidars) != 1:
        raise ValueError("Expected exactly one LiDAR")
    lidar = lidars[0]
    components = rover.get_components_by_class(unreal.SceneComponent)

    def find(name):
        key = str(name).lower().replace("_", "")
        selected = [c for c in components if c.get_name().lower().replace("_", "") == key]
        if len(selected) != 1:
            raise ValueError("Expected exactly one component named " + str(name))
        return selected[0]

    follow = str(lidar.get_editor_property("follow_component_name"))
    return world, rover, lidar, find("base_link"), lidar if follow.lower() in ("none", "") else find(follow)


def _sample(state):
    sample_started = state["now"]()
    body = frames.map_frame(state["body"])
    mount = frames.map_frame(state["mount"])
    relative = frames.relative_frame(body, mount)
    translation, rotation = _difference(state["reference"], relative)
    clock = getattr(state["unreal"], "GncSimTimeLibrary", None)
    get_stamp = getattr(clock, "get_sim_time_ns_string", None)
    stamp = str(get_stamp(state["world"])) if callable(get_stamp) else None
    if stamp is not None and (not stamp.isascii() or not stamp.isdigit() or len(stamp) > 19
                              or not 0 < int(stamp) <= 2**63 - 1):
        raise ValueError("Invalid simulation clock stamp")
    heading = math.atan2(body[1][0], body[0][0])
    sample_finished = state["now"]()
    state["samples"].append({"elapsed_s": max(0.0, sample_finished - state["started"]),
                             "processing_s": max(0.0, sample_finished - sample_started),
                             "stamp_ns": stamp, "heading_rad": heading,
                             "translation_difference_m": translation, "rotation_difference_deg": rotation,
                             "body_world": body, "mount_to_body": relative})


def _finish(state, reason, error=None):
    if getattr(builtins, _KEY, None) is not state:
        return None
    setattr(builtins, _KEY, None)
    state["unreal"].unregister_slate_post_tick_callback(state["handle"])
    samples = state["samples"]
    heading0 = samples[0]["heading_rad"] if samples else 0.0
    turns = [abs(math.degrees(math.atan2(math.sin(s["heading_rad"] - heading0),
                                        math.cos(s["heading_rad"] - heading0)))) for s in samples]
    relative0 = samples[0]["mount_to_body"] if samples else None
    changes = [_difference(relative0, s["mount_to_body"]) for s in samples] if relative0 else []
    stamps = [s["stamp_ns"] for s in samples if s["stamp_ns"] is not None]
    summary = {"reason": reason, "error": error, "world": state["world_path"],
               "session_id_at_start": state["session_id"], "mount": state["mount_name"],
               "sample_count": len(samples), "unique_stamp_count": len(set(stamps)),
               "duration_s": max(0.0, state["now"]() - state["started"]),
               "max_sample_processing_s": max((s["processing_s"] for s in samples), default=None),
               "max_heading_change_deg": max(turns) if turns else None,
               "max_mount_translation_difference_m": max((s["translation_difference_m"] for s in samples), default=None),
               "max_mount_rotation_difference_deg": max((s["rotation_difference_deg"] for s in samples), default=None),
               "max_mount_translation_change_from_first_m": max((v[0] for v in changes), default=None),
               "max_mount_rotation_change_from_first_deg": max((v[1] for v in changes), default=None),
               "first_stamp_ns": samples[0]["stamp_ns"] if samples else None,
               "last_stamp_ns": samples[-1]["stamp_ns"] if samples else None,
               "limits": "Slate post-tick samples are not LiDAR request or GPU render poses; matching stamps "
                         "do not establish simultaneity. The observer samples at a bounded interval and checks "
                         "the service session at start only; unsampled motion and future scans are not covered."}
    path = state["output_dir"] / ("lidar-montaj-" + uuid.uuid4().hex + ".json")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump({"summary": summary, "reference_to_body": state["reference"], "samples": samples},
                      stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
        summary["report_path"] = str(path)
    except (OSError, ValueError) as exc:
        summary["report_error"] = str(exc)[:256]
    print("MARS_LIDAR_MOUNT_RESULT:", json.dumps(summary, ensure_ascii=False, allow_nan=False))
    return summary


def start(config_path, alignment, *, duration_s=90, interval_s=0.1, unreal_module=None,
          get_snapshot=None, monotonic=None):
    """Start bounded, PIE-only observation; caller must supervise any separate drive."""
    if getattr(builtins, _KEY, None) is not None:
        raise RuntimeError("Mount observation already active; call stop() first")
    if (type(duration_s) not in (int, float) or not math.isfinite(duration_s) or not 1 <= duration_s <= 120
            or type(interval_s) not in (int, float) or not math.isfinite(interval_s) or not 0.05 <= interval_s <= 1):
        raise ValueError("Use duration 1..120 s and interval 0.05..1 s")
    if unreal_module is None:
        import unreal as unreal_module
    unreal = unreal_module
    get_snapshot = get_snapshot or _get_snapshot
    now = monotonic or time.monotonic
    snapshot = get_snapshot()
    session = snapshot.get("session_id")
    mission = snapshot.get("mission")
    speed = snapshot.get("speed_estimate_m_s")
    wheels = snapshot.get("wheel_command_m_s") or {}
    if (not isinstance(alignment, dict) or not isinstance(session, str) or not session
            or session != alignment.get("session_id") or snapshot.get("state") not in ("idle", "new_session_requires_goal")
            or snapshot.get("pose_fresh") is not True or snapshot.get("capture_clock_advancing") is not True
            or snapshot.get("position_source") != "simulation telemetry"
            or type(speed) not in (int, float) or not math.isfinite(speed) or not 0 <= speed <= 0.01
            or (mission is not None and (not isinstance(mission, dict) or mission.get("closed") is not True))
            or any(type(wheels.get(k)) not in (int, float) or not math.isfinite(wheels[k]) or abs(wheels[k]) > 1e-9
                   for k in ("FL", "FR", "BL", "BR"))):
        raise ValueError("Matching alignment session, stationary simulation pose, and zero wheels required")
    config_path = Path(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    manifest = snapshot.get("terrain_manifest_sha256")
    if (config.get("schema_version") != 1 or not isinstance(manifest, str) or not manifest
            or config.get("manifest_sha256") != manifest):
        raise ValueError("Sensor configuration does not match the running terrain manifest")
    settings = config["lidar"]
    reference = _matrix(settings["to_body"])
    world, rover, lidar, body, mount = _components(unreal)
    world_path = world.get_path_name()
    if alignment.get("world") != world_path or alignment.get("rover") != rover.get_name():
        raise ValueError("Alignment refers to a different Play world or rover")
    if settings.get("sensor_id") != lidar.get_editor_property("sensor_id"):
        raise ValueError("LiDAR sensor ID differs from the saved configuration")
    state = {"unreal": unreal, "world": world, "rover": rover, "body": body, "mount": mount,
             "mount_name": mount.get_name(), "world_path": world_path, "reference": reference, "session_id": session,
             "now": now, "started": now(), "next_sample": 0.0, "interval": float(interval_s),
             "duration": float(duration_s), "output_dir": config_path.parent, "samples": [], "handle": None}
    _sample(state)  # Validate the live frames before registering any callback.

    def tick(_delta):
        if getattr(builtins, _KEY, None) is not state:
            return
        elapsed = now() - state["started"]
        if elapsed >= state["duration"] or len(state["samples"]) >= 2400:
            _finish(state, "duration_or_sample_limit")
            return
        if elapsed < state["next_sample"]:
            return
        try:
            current = unreal.EditorLevelLibrary.get_pie_worlds(False)
            if len(current) != 1 or current[0].get_path_name() != state["world_path"]:
                _finish(state, "play_world_changed")
                return
            _sample(state)
            state["next_sample"] = elapsed + state["interval"]
        except Exception as exc:
            _finish(state, "sampling_error", str(exc)[:256])

    state["callback"] = tick
    state["next_sample"] = state["interval"]
    state["handle"] = unreal.register_slate_post_tick_callback(tick)
    setattr(builtins, _KEY, state)
    result = {"started": True, "world": world_path, "session_id": session, "mount": mount.get_name(),
              "duration_s": duration_s, "interval_s": interval_s,
              "scope": "current PIE objects; no motion commands or scene changes"}
    print("MARS_LIDAR_MOUNT_START:", json.dumps(result, ensure_ascii=False))
    return result


def stop():
    """Unregister the observer and save its bounded samples in the config directory."""
    state = getattr(builtins, _KEY, None)
    if state is None:
        raise RuntimeError("No active mount observation")
    return _finish(state, "stopped")
