"""Compare an idle rover's display LiDAR scan with current PIE collision.

This is a read-only diagnostic: the display stream is downsampled/rounded and
uses the current body pose, not the scan's capture-time pose. It cannot certify
sensor calibration, dynamic obstacles, or navigation safety.
"""

import json
import math
import statistics
from pathlib import Path
from urllib.request import urlopen


def _http_json(url):
    with urlopen(url, timeout=3) as response:
        return json.load(response)


def _telemetry_pose(telemetry):
    """Match the adapter's Unreal-to-local ENU pose, using stdlib only."""
    names = ("x", "y", "z", "roll", "pitch", "yaw")
    values = [telemetry[name] for name in names]
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError("Telemetry pose is missing or non-finite")
    x, y, z, roll, pitch, yaw = values
    r, p, h = map(math.radians, (roll, pitch, yaw))
    cr, sr, cp, sp, ch, sh = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(h), math.sin(h)
    forward = [-cp * ch, cp * sh, sp]
    up = [cr * sp * ch + sr * sh, ch * sr - cr * sp * sh, cr * cp]
    left = [up[1] * forward[2] - up[2] * forward[1],
            up[2] * forward[0] - up[0] * forward[2],
            up[0] * forward[1] - up[1] * forward[0]]
    return [[forward[i], left[i], up[i], [-x / 100, y / 100, z / 100][i]] for i in range(3)]


def _pose_difference(scene, telemetry):
    delta = [scene[i][3] - telemetry[i][3] for i in range(3)]
    trace = sum(scene[i][j] * telemetry[i][j] for i in range(3) for j in range(3))
    angle = math.degrees(math.acos(max(-1.0, min(1.0, (trace - 1) / 2))))
    return {"translation_m": delta, "distance_m": math.sqrt(sum(v * v for v in delta)), "rotation_deg": angle}


def _world_point(body, point):
    return [sum(body[i][j] * point[j] for j in range(3)) + body[i][3] for i in range(3)]


def _trace(unreal, world, rover, point):
    hit = unreal.SystemLibrary.line_trace_single(
        world_context_object=world,
        start=unreal.Vector(-100 * point[0], 100 * point[1], 100 * (point[2] + 20)),
        end=unreal.Vector(-100 * point[0], 100 * point[1], 100 * (point[2] - 20)),
        trace_channel=unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
        trace_complex=True, actors_to_ignore=[rover],
        draw_debug_type=unreal.DrawDebugTrace.NONE, ignore_self=False,
    )
    if hit is None:
        return None
    fields = hit.to_tuple()
    if len(fields) != 18:
        raise ValueError("Unsupported Unreal HitResult layout")
    if fields[0] is not True:
        return None
    hit_point, actor = fields[5], fields[9]
    z = float(hit_point.z) / 100
    if not math.isfinite(z):
        raise ValueError("Collision trace returned a non-finite height")
    return {"collision_z_m": z, "lidar_minus_collision_m": point[2] - z,
            "actor": actor.get_name() if actor else None,
            "actor_class": actor.get_class().get_name() if actor else None}


def probe_idle(sensor_config_path, *, unreal_module=None, fetch_json=None):
    """Print one bounded comparison of a fresh, idle PIE LiDAR display scan."""
    if unreal_module is None:
        import unreal as unreal_module
    import mars_sensor_setup as setup

    unreal, get = unreal_module, fetch_json or _http_json
    config = json.loads(Path(sensor_config_path).read_text(encoding="utf-8-sig"))
    worlds = unreal.EditorLevelLibrary.get_pie_worlds(False)
    if len(worlds) != 1:
        raise ValueError("Start exactly one local Unreal Play session before this probe")
    world = worlds[0]
    pawns = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Pawn)
    rovers = [a for a in pawns if a.get_class().get_name().startswith("Leo_Raph")]
    if len(rovers) != 1:
        raise ValueError("Expected exactly one Leo_Raph rover in the Play world")
    rover = rovers[0]
    components = rover.get_components_by_class(unreal.SceneComponent)

    def find(name):
        key = str(name).lower().replace("_", "")
        matches = [c for c in components if c.get_name().lower().replace("_", "") == key]
        if len(matches) != 1:
            raise ValueError(f"Cannot uniquely resolve rover component {name}")
        return matches[0]

    lidars = rover.get_components_by_class(unreal.UnrealLidarCam)
    if len(lidars) != 1:
        raise ValueError("Expected exactly one LiDAR on the rover")
    lidar = lidars[0]
    follow = str(lidar.get_editor_property("follow_component_name"))
    mount = lidar if follow.lower() in ("", "none") else find(follow)

    snapshot = get("http://127.0.0.1:8766/mission/snapshot")
    if (snapshot.get("state") != "idle" or not snapshot.get("pose_fresh")
            or not snapshot.get("capture_clock_advancing")):
        raise ValueError("The rover must be idle with a fresh, advancing pose")
    speed = snapshot.get("speed_estimate_m_s")
    if type(speed) not in (int, float) or not math.isfinite(speed) or not 0 <= speed <= 0.01:
        raise ValueError("Wait for a stationary speed estimate of at most 0.01 m/s")
    before = get("http://127.0.0.1:8765/status")
    scan = get("http://127.0.0.1:8766/dashboard/lidar")
    body = setup.map_frame(find("base_link"))
    sensor_to_body = setup.relative_frame(body, setup.map_frame(mount))
    after = get("http://127.0.0.1:8765/status")
    if not before.get("connected") or not after.get("connected") or before.get("connection_id") != after.get("connection_id"):
        raise ValueError("Rover connection changed during the probe")
    if any(type(after.get("wheel_command_m_s", {}).get(k)) not in (float, int)
           or abs(after["wheel_command_m_s"][k]) > 1e-9 for k in ("FL", "FR", "BL", "BR")):
        raise ValueError("The rover has a nonzero or missing wheel command")
    telemetry = after.get("telemetry_unreal") or {}
    angular = [telemetry.get(k) for k in ("wx", "wy", "wz")]
    if any(type(v) not in (float, int) or not math.isfinite(v) or abs(v) > 0.01 for v in angular):
        raise ValueError("Wait until reported angular velocity components are near zero")
    if (type(after.get("telemetry_age_s")) not in (float, int)
            or not math.isfinite(after["telemetry_age_s"]) or not 0 <= after["telemetry_age_s"] <= 0.4):
        raise ValueError("Rover telemetry became too old during the probe; retry while idle")
    stamp = int(scan["stamp_ns"])
    lag = (int(telemetry["t_ns"]) - stamp) / 1e9
    if not -0.001 <= lag <= 0.4:
        raise ValueError(f"Display LiDAR capture is {lag:.3f} s behind pose; retry while idle")
    points, count = scan.get("points"), scan.get("count")
    if (scan.get("frame") != "rover" or type(points) is not list or type(count) is not int
            or len(points) != count * 3 or count > 5000):
        raise ValueError("Unexpected LiDAR display payload")

    bins = [(3.0, 5.0), (5.0, 6.5), (6.5, 8.0)]
    candidates = [[] for _ in bins]
    origin = [sensor_to_body[i][3] for i in range(3)]
    for index in range(count):
        point = points[index * 3 : index * 3 + 3]
        if any(type(v) not in (float, int) or not math.isfinite(v) for v in point):
            continue
        distance = math.sqrt(sum((point[i] - origin[i]) ** 2 for i in range(3)))
        for n, (low, high) in enumerate(bins):
            if low <= distance < high:
                candidates[n].append((distance, point))
                break

    results = []
    for (low, high), group in zip(bins, candidates):
        # Evenly cover the display order; never select on residual magnitude.
        count_sampled = min(16, len(group))
        chosen = [group[round(i * (len(group) - 1) / max(1, count_sampled - 1))] for i in range(count_sampled)]
        hits, misses = [], 0
        for distance, point in chosen:
            world_point = _world_point(body, point)
            hit = _trace(unreal, world, rover, world_point)
            if hit is None:
                misses += 1
            else:
                hits.append({"sensor_range_m": distance, "local_xy_m": world_point[:2],
                             "lidar_z_m": world_point[2], **hit})
        landscape = [h for h in hits if h["actor_class"] in ("Landscape", "LandscapeStreamingProxy")]
        deltas = [h["lidar_minus_collision_m"] for h in landscape]
        results.append({"range_m": [low, high], "candidates": len(group), "tested": count_sampled,
                        "misses": misses, "non_landscape_hits": len(hits) - len(landscape),
                        "landscape_hits": len(landscape),
                        "median_lidar_minus_collision_m": statistics.median(deltas) if deltas else None,
                        "minimum_lidar_minus_collision_m": min(deltas) if deltas else None,
                        "maximum_lidar_minus_collision_m": max(deltas) if deltas else None,
                        "below_minus_015m": sum(v < -0.15 for v in deltas), "examples": landscape[:3]})
    expected = config["lidar"]["to_body"]
    matrix_difference = max(abs(sensor_to_body[i][j] - expected[i][j]) for i in range(3) for j in range(4))
    result = {"world_path": world.get_path_name(), "rover": rover.get_name(),
              "mode": str(lidar.get_editor_property("mode")), "follow_component": follow,
              "sensor_id_scene": int(lidar.get_editor_property("sensor_id")),
              "sensor_id_config": config["lidar"]["sensor_id"],
              "scan_stamp_ns": str(stamp), "telemetry_stamp_ns": str(telemetry["t_ns"]),
              "scan_to_telemetry_s": lag, "telemetry_age_s": after["telemetry_age_s"],
              "speed_estimate_m_s": speed, "angular_velocity_raw": angular,
              "telemetry_vs_current_body": _pose_difference(body, _telemetry_pose(telemetry)),
              "runtime_sensor_matrix_max_difference": matrix_difference,
              "display_points": count, "range_bins": results,
              "limits": "Display points are rounded/downsampled; current pose and current collision are used. "
                        "Stationarity is screened but capture-time pose and render geometry are not verified."}
    print("MARS_LIDAR_IDLE_PROBE:", json.dumps(result, ensure_ascii=False, allow_nan=False))
    return result
