"""Temporarily change tick groups on the current PIE rover for an A/B test.

This is a simulation experiment, not a proven sensor fix. It changes only live
PIE objects, sends no goal or stop, and stopping Play discards the changes.
The rover actor is placed in PostPhysics and the navigation LiDAR and camera
components in PostUpdateWork. Blueprint telemetry and actual render execution
must still be measured; control timing can change by a frame.
"""

import json
import math
from urllib.request import urlopen


def _http_json(url):
    with urlopen(url, timeout=3) as response:
        return json.load(response)


def _zero_wheels(value):
    return isinstance(value, dict) and all(
        type(value.get(k)) in (int, float) and math.isfinite(value[k]) and abs(value[k]) <= 1e-9
        for k in ("FL", "FR", "BL", "BR")
    )


def _stationary(get_json):
    snapshot = get_json("http://127.0.0.1:8766/mission/snapshot")
    bridge = get_json("http://127.0.0.1:8765/status")
    mission = snapshot.get("mission")
    speed = snapshot.get("speed_estimate_m_s")
    if (snapshot.get("state") not in ("idle", "new_session_requires_goal")
            or snapshot.get("pose_fresh") is not True or snapshot.get("capture_clock_advancing") is not True
            or snapshot.get("position_source") != "simulation telemetry"
            or not isinstance(snapshot.get("session_id"), str) or not snapshot["session_id"]
            or (mission is not None and (not isinstance(mission, dict) or mission.get("closed") is not True))
            or type(speed) not in (int, float) or not math.isfinite(speed) or not 0 <= speed <= 0.01
            or not _zero_wheels(snapshot.get("wheel_command_m_s"))):
        raise ValueError("Rover must be idle with a fresh advancing pose and zero wheel commands")
    age = bridge.get("telemetry_age_s")
    telemetry = bridge.get("telemetry_unreal") or {}
    angular = [telemetry.get(k) for k in ("wx", "wy", "wz")]
    if (bridge.get("connected") is not True or bridge.get("telemetry_format") != "unreal-tr-v1"
            or type(age) not in (int, float) or not math.isfinite(age) or not 0 <= age <= 0.3
            or not _zero_wheels(bridge.get("wheel_command_m_s"))
            or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 0.01 for v in angular)):
        raise ValueError("Fresh connected stationary tr-TR rover telemetry is required")
    pose_stamp = (snapshot.get("live_pose") or {}).get("stamp_ns")
    bridge_stamp = telemetry.get("t_ns")
    if (not isinstance(pose_stamp, (str, int)) or isinstance(pose_stamp, bool)
            or not str(pose_stamp).isascii() or not str(pose_stamp).isdigit()
            or not isinstance(bridge_stamp, (str, int)) or isinstance(bridge_stamp, bool)
            or not str(bridge_stamp).isascii() or not str(bridge_stamp).isdigit()
            or int(pose_stamp) <= 0 or int(bridge_stamp) <= 0
            or abs(int(pose_stamp) - int(bridge_stamp)) > 500_000_000):
        raise ValueError("Snapshot and bridge timestamps are missing or inconsistent")
    return snapshot


def _group(obj, prop):
    return obj.get_editor_property(prop).get_editor_property("tick_group")


def apply(*, unreal_module=None, get_json=None):
    if unreal_module is None:
        import unreal as unreal_module
    if get_json is None:
        get_json = _http_json
    unreal = unreal_module
    from mars_lidar_pose_diagnostics import _rover

    world, rover = _rover(unreal)
    lidars = rover.get_components_by_class(unreal.UnrealLidarCam)
    navcams = [c for c in rover.get_components_by_class(unreal.UnrealStereoCam)
               if c.get_name() == "NavCam_UnrealStereoCam"]
    if len(lidars) != 1 or len(navcams) != 1:
        raise ValueError("Expected one LiDAR and the NavCam_UnrealStereoCam component")
    lidar, camera = lidars[0], navcams[0]
    if (not rover.is_actor_tick_enabled() or not lidar.is_component_tick_enabled()
            or not camera.is_component_tick_enabled()):
        raise ValueError("Rover, LiDAR, and navigation-camera ticks must be enabled")
    snapshot = _stationary(get_json)
    target = [("actor", rover, "primary_actor_tick", unreal.TickingGroup.TG_POST_PHYSICS),
              ("lidar", lidar, "primary_component_tick", unreal.TickingGroup.TG_POST_UPDATE_WORK),
              ("camera", camera, "primary_component_tick", unreal.TickingGroup.TG_POST_UPDATE_WORK)]
    original = [(label, obj, prop, _group(obj, prop), desired) for label, obj, prop, desired in target]
    changed = []
    try:
        for label, obj, prop, before, desired in original:
            changed.append((obj, prop, before))
            obj.set_tick_group(desired)
            if _group(obj, prop) != desired:
                raise RuntimeError(f"Tick group did not update for {label}")
    except BaseException as error:
        failures = []
        for obj, prop, before in reversed(changed):
            try:
                obj.set_tick_group(before)
                if _group(obj, prop) != before:
                    raise RuntimeError("tick group did not restore")
            except Exception as failure:
                failures.append(str(failure))
        if failures:
            raise RuntimeError("Tick rollback failed; stop Unreal Play: " + "; ".join(failures)) from error
        raise
    result = {"world": world.get_path_name(), "rover": rover.get_name(),
              "session_id": snapshot.get("session_id"),
              "groups": {label: {"before": str(before), "after": str(_group(obj, prop))}
                         for label, obj, prop, before, _ in original},
              "scope": "current Play objects only; stop Play to restore",
              "limits": "Minimum groups changed; Blueprint telemetry phase and GPU render pose are unverified."}
    print("MARS_TICK_ALIGNMENT:", json.dumps(result, ensure_ascii=False))
    return result
