"""Read-only Unreal collision probes for the recorded blocked-goal samples."""

import json
import math
from pathlib import Path


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
