"""Read-only Unreal collision probes for the recorded blocked-goal samples."""

import json
import math
from pathlib import Path
import statistics


def _trace(unreal, world, x_m, y_m, dem_z_m, lidar_z_m, *, complex_trace):
    x_cm, y_cm = -100.0 * x_m, 100.0 * y_m
    top_cm = 100.0 * (max(dem_z_m, lidar_z_m) + 20.0)
    bottom_cm = 100.0 * (min(dem_z_m, lidar_z_m) - 20.0)
    hit = unreal.SystemLibrary.line_trace_single(
        world_context_object=world,
        start=unreal.Vector(x_cm, y_cm, top_cm), end=unreal.Vector(x_cm, y_cm, bottom_cm),
        trace_channel=unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
        trace_complex=complex_trace, actors_to_ignore=[],
        draw_debug_type=unreal.DrawDebugTrace.NONE, ignore_self=False,
    )
    if hit is None:
        return {"blocking": False}
    fields = hit.to_tuple()
    if len(fields) != 18:
        raise RuntimeError("Unsupported Unreal HitResult layout; cannot interpret collision trace")
    if fields[0] is not True:
        return {"blocking": False}
    point, actor = fields[5], fields[9]
    if not all(math.isfinite(v) for v in (point.x, point.y, point.z)):
        raise RuntimeError("Unreal returned a non-finite collision point")
    z_m = point.z / 100.0
    return {"blocking": True, "initial_overlap": bool(fields[1]),
            "collision_z_m": z_m, "collision_vs_dem_m": z_m - dem_z_m,
            "collision_vs_lidar_m": z_m - lidar_z_m,
            "actor_name": actor.get_name() if actor else None,
            "actor_class": actor.get_class().get_name() if actor else None}


def probe_goal(report_path, *, unreal_module=None):
    """Trace sample XYs that first blocked the goal; print and return a JSON result.

    This measures the currently loaded world's collision at those coordinates.
    It does not reconstruct a past moving sensor capture or alter the world.
    """
    if unreal_module is None:
        import unreal as unreal_module

    unreal = unreal_module
    report = json.loads(Path(report_path).read_text(encoding="utf-8-sig"))
    diag = report.get("obstacle_diagnostics") or {}
    failure = diag.get("last_planning_failure") or {}
    goal = failure.get("goal") or {}
    contributors = goal.get("contributors_raw_row_col")
    if not diag.get("enabled") or not goal.get("blocked") or not isinstance(contributors, list):
        raise ValueError("Report does not contain a blocked goal with recorded contributors")
    mission_id = failure.get("mission_id")
    missions = [m for m in report.get("missions", []) if m.get("mission_id") == mission_id]
    if len(missions) != 1:
        raise ValueError("Recorded planning failure does not identify exactly one retained mission")

    wanted = {tuple(cell) for cell in contributors}
    matched = {}
    for frame in diag.get("frames", []):
        for cell in frame.get("new_cells", []):
            key = tuple(cell.get("cell_row_col", ()))
            if key in wanted and key not in matched:
                matched[key] = (frame, cell)

    pie_worlds = unreal.EditorLevelLibrary.get_pie_worlds(False)
    if len(pie_worlds) > 1:
        raise RuntimeError("Multiple PIE worlds are open; choose a single local Play session")
    world = pie_worlds[0] if pie_worlds else unreal.EditorLevelLibrary.get_editor_world()
    if world is None:
        raise RuntimeError("No accessible Unreal world for collision probing")

    samples = []
    for key in sorted(matched)[:8]:
        frame, cell = matched[key]
        point = cell.get("sample_world_m")
        residual = cell.get("sample_residual_m")
        if (not isinstance(point, list) or len(point) != 3 or
                not all(type(v) in (int, float) and math.isfinite(v) for v in (*point, residual))):
            raise ValueError("Recorded obstacle sample is not finite XYZ and residual data")
        x, y, lidar_z = map(float, point)
        dem_z = lidar_z - residual
        samples.append({
            "cell_row_col": list(key), "source": frame.get("source"), "frame_id": frame.get("frame_id"),
            "stamp_ns": str(frame.get("stamp_ns")), "frame_session_id": frame.get("session_id"),
            "frame_mission_id": frame.get("mission_id"), "local_xy_m": [x, y],
            "lidar_z_m": lidar_z, "dem_z_m": dem_z,
            "traces": {"simple": _trace(unreal, world, x, y, dem_z, lidar_z, complex_trace=False),
                       "complex": _trace(unreal, world, x, y, dem_z, lidar_z, complex_trace=True)},
        })
    result = {"world_type": "PIE" if pie_worlds else "editor", "world_path": world.get_path_name(),
              "mission_id": mission_id, "goal_xy_m": missions[0].get("goal"),
              "frames_evicted": diag.get("frames_evicted"),
              "truncated_frames": sum(bool(f.get("new_cells_truncated")) for f in diag.get("frames", [])),
              "samples": samples, "samples_omitted": max(0, len(matched) - len(samples)),
              "missing_contributors": [list(cell) for cell in sorted(wanted - set(matched))]}
    print("MARS_LIDAR_COLLISION:", json.dumps(result, ensure_ascii=False, allow_nan=False))
    return result


def probe_mission(report_path, *, mission_id=None, max_samples=32, unreal_module=None):
    """Trace recorded LiDAR map changes, even if the mission never reached its goal.

    This reads a saved diagnostic export and traces the current world. The
    returned comparisons do not reconstruct the GPU render or prove that a
    whole cell is clear. No rover commands or map changes are made.
    """
    if type(max_samples) is not int or not 1 <= max_samples <= 128:
        raise ValueError("max_samples must be an integer from 1 to 128")
    if unreal_module is None:
        import unreal as unreal_module
    unreal = unreal_module
    report = json.loads(Path(report_path).read_text(encoding="utf-8-sig"))
    diag = report.get("obstacle_diagnostics") or {}
    missions = report.get("missions")
    if not diag.get("enabled") or not isinstance(missions, list) or not missions:
        raise ValueError("Report must contain retained missions and obstacle diagnostics")
    if mission_id is None:
        mission_id = missions[-1].get("mission_id") if isinstance(missions[-1], dict) else None
    matching = [m for m in missions if isinstance(m, dict) and m.get("mission_id") == mission_id]
    if not isinstance(mission_id, str) or not mission_id or len(matching) != 1:
        raise ValueError("Mission must identify exactly one retained mission")
    session_id = matching[0].get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Mission session ID is missing")
    frames = [frame for frame in diag.get("frames", [])
              if isinstance(frame, dict) and frame.get("source") == "lidar"
              and frame.get("mission_id") == mission_id and frame.get("session_id") == session_id]
    candidates = []
    for frame in frames:
        cells = frame.get("new_cells")
        if not isinstance(cells, list):
            raise ValueError("Recorded LiDAR cells are invalid")
        candidates.extend((frame, cell) for cell in cells)
    if not candidates:
        raise ValueError("No retained newly occupied LiDAR cells for this mission")

    pie_worlds = unreal.EditorLevelLibrary.get_pie_worlds(False)
    if len(pie_worlds) > 1:
        raise RuntimeError("Multiple PIE worlds are open; choose a single local Play session")
    world = pie_worlds[0] if pie_worlds else unreal.EditorLevelLibrary.get_editor_world()
    if world is None:
        raise RuntimeError("No accessible Unreal world for collision probing")

    samples = []
    for frame, cell in candidates[:max_samples]:
        if not isinstance(cell, dict):
            raise ValueError("Recorded obstacle sample is not an object")
        point, residual = cell.get("sample_world_m"), cell.get("sample_residual_m")
        if (not isinstance(point, list) or len(point) != 3
                or not all(type(v) in (int, float) and math.isfinite(v) for v in (*point, residual))):
            raise ValueError("Recorded obstacle sample is not finite XYZ and residual data")
        x, y, lidar_z = map(float, point)
        dem_z = lidar_z - residual
        trace = _trace(unreal, world, x, y, dem_z, lidar_z, complex_trace=True)
        samples.append({"frame_id": frame.get("frame_id"), "stamp_ns": frame.get("stamp_ns"),
                        "cell_row_col": cell.get("cell_row_col"), "local_xy_m": [x, y],
                        "lidar_minus_dem_m": residual, "trace": trace})

    def stats(values):
        return {"min": min(values), "median": statistics.median(values), "max": max(values)} if values else None

    summaries = []
    for frame in frames:
        frame_samples = [sample for sample in samples if sample["frame_id"] == frame.get("frame_id")
                         and sample["stamp_ns"] == frame.get("stamp_ns")]
        if not frame_samples:
            continue
        hits = [sample["trace"] for sample in frame_samples if sample["trace"].get("blocking")]
        actor_classes = {}
        for hit in hits:
            key = hit.get("actor_class") or "unknown"
            actor_classes[key] = actor_classes.get(key, 0) + 1
        summaries.append({"frame_id": frame.get("frame_id"), "stamp_ns": frame.get("stamp_ns"),
                          "recorded_new_cells": frame.get("new_cells_total"),
                          "samples_tested": len(frame_samples), "trace_misses": len(frame_samples) - len(hits),
                          "actor_classes": actor_classes,
                          "collision_minus_dem_m": stats([h["collision_vs_dem_m"] for h in hits]),
                          "lidar_minus_collision_m": stats([-h["collision_vs_lidar_m"] for h in hits]),
                          "examples": frame_samples[:3]})
    result = {"world_type": "PIE" if pie_worlds else "editor", "world_path": world.get_path_name(),
              "mission_id": mission_id, "session_id": session_id,
              "terrain_manifest_sha256": report.get("terrain_manifest_sha256"),
              "frames_evicted": diag.get("frames_evicted"),
              "truncated_frames": sum(bool(f.get("new_cells_truncated")) for f in frames),
              "recorded_samples": len(candidates), "samples_tested": len(samples),
              "samples_omitted": max(0, len(candidates) - len(samples)), "frames": summaries,
              "limits": "Current complex collision at representative recorded points; not capture-time "
                        "GPU geometry, a full scan, or proof that an entire map cell is clear."}
    print("MARS_LIDAR_MISSION_COLLISION:", json.dumps(result, ensure_ascii=False, allow_nan=False))
    return result
