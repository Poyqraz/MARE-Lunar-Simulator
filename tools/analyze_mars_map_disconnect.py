"""Reconstruct a recorded Mars navigation map offline without commanding the rover.

Counterfactual maps are evidence about the recorded planner inputs, not evidence
that any obstacle is false or that a route is safe to drive.
"""

import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mars_rover.planning import NoRoute, TerrainMap  # noqa: E402


class IncompleteEvidence(ValueError):
    pass


def _stamp(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise IncompleteEvidence("A capture timestamp is missing or invalid")
    raw = str(value)
    if not raw.isascii() or not raw.isdigit() or int(raw) <= 0:
        raise IncompleteEvidence("A capture timestamp is missing or invalid")
    return int(raw)


def _route(grid, raw, start, goal):
    trial = copy.copy(grid)
    trial.raw_blocked = raw.copy()
    trial.blocked = trial._inflate(trial.raw_blocked)
    start_blocked = bool(trial.blocked[trial.cell(start)])
    goal_blocked = bool(trial.blocked[trial.cell(goal)])
    try:
        route = trial.plan(start, goal)
    except NoRoute as error:
        return {"route_found": False, "reason": str(error), "start_blocked": start_blocked,
                "goal_blocked": goal_blocked}
    return {"route_found": True, "reason": None, "start_blocked": start_blocked,
            "goal_blocked": goal_blocked, "route_points": len(route)}


def analyze(export, grid, mission_id=None):
    """Rebuild the static grid and all recorded additions through the failure.

    Fail closed if this export cannot establish a complete sequence. The
    caller is responsible for loading the same planner code and limits as the
    recording; the export does not include their version or limit values.
    """
    manifest_hash = export.get("terrain_manifest_sha256")
    if (not isinstance(manifest_hash, str) or len(manifest_hash) != 64
            or grid.manifest_sha256 != manifest_hash):
        raise IncompleteEvidence("The terrain manifest does not match the mission export")
    diag = export.get("obstacle_diagnostics") or {}
    if diag.get("enabled") is not True or diag.get("frames_evicted") != 0:
        raise IncompleteEvidence("Obstacle diagnostics are missing or frames were evicted")
    failure = diag.get("last_planning_failure") or {}
    selected = mission_id or failure.get("mission_id")
    if not isinstance(selected, str) or failure.get("mission_id") != selected:
        raise IncompleteEvidence("The recorded planning failure does not match this mission")
    missions = [m for m in export.get("missions", []) if m.get("mission_id") == selected]
    if len(missions) != 1:
        raise IncompleteEvidence("The mission is missing or ambiguous")
    mission = missions[0]
    end_pose = mission.get("end_pose") or {}
    if (mission.get("status") != "blocked" or mission.get("error") != failure.get("error")
            or _stamp(end_pose.get("stamp_ns")) != _stamp(failure.get("stamp_ns"))):
        raise IncompleteEvidence("The mission endpoint does not match the planning failure")
    start = tuple(float(v) for v in end_pose["position_m"][:2])
    goal = tuple(float(v) for v in mission["goal"])
    first, last = grid.cell(start), grid.cell(goal)
    if (list(first) != (failure.get("start") or {}).get("cell_row_col")
            or list(last) != (failure.get("goal") or {}).get("cell_row_col")):
        raise IncompleteEvidence("Failure cells do not match the recorded pose and goal")

    revision = failure.get("map_revision")
    if type(revision) is not int or revision < 0:
        raise IncompleteEvidence("The failure map revision is invalid")
    frames = diag.get("frames")
    if not isinstance(frames, list) or any(not isinstance(frame, dict) for frame in frames):
        raise IncompleteEvidence("The obstacle frame list is missing")
    selected_frames = [f for f in frames if type(f.get("map_revision")) is int
                       and 0 < f["map_revision"] <= revision]
    if len(selected_frames) != revision:
        raise IncompleteEvidence("The obstacle map revision history is incomplete")
    selected_frames.sort(key=lambda frame: frame["map_revision"])
    if [f["map_revision"] for f in selected_frames] != list(range(1, revision + 1)):
        raise IncompleteEvidence("The obstacle map revisions are missing or duplicated")

    by_source = {"lidar": [], "ground_truth": [], "stereo": []}
    seen = set()
    height, width = grid.raw_blocked.shape
    for frame in selected_frames:
        source, cells = frame.get("source"), frame.get("new_cells")
        if (source not in by_source or "collection_error" in frame or not isinstance(cells, list)
                or type(frame.get("new_cells_total")) is not int or frame["new_cells_total"] != len(cells)
                or frame.get("new_cells_truncated") != 0):
            raise IncompleteEvidence("At least one obstacle frame is incomplete or has an unknown source")
        for item in cells:
            cell = item.get("cell_row_col") if isinstance(item, dict) else None
            if (not isinstance(cell, list) or len(cell) != 2 or any(type(x) is not int for x in cell)
                    or not (0 <= cell[0] < height and 0 <= cell[1] < width)):
                raise IncompleteEvidence("An obstacle cell is invalid")
            row, col = cell
            if (row, col) in seen or grid.raw_blocked[row, col]:
                raise IncompleteEvidence("Recorded cells do not match the static map and unique revisions")
            seen.add((row, col))
            by_source[source].append((row, col))

    def raw_without(excluded):
        raw = grid.raw_blocked.copy()
        for source, cells in by_source.items():
            if source != excluded:
                for row, col in cells:
                    raw[row, col] = True
        return raw

    recorded = _route(grid, raw_without(None), start, goal)
    if (recorded["route_found"] or recorded["reason"] != failure.get("error")
            or recorded["start_blocked"] != (failure.get("start") or {}).get("blocked")
            or recorded["goal_blocked"] != (failure.get("goal") or {}).get("blocked")):
        raise IncompleteEvidence("Reconstructed planner result does not match the recorded failure")
    return {
        "status": "reconstructed",
        "mission_id": selected,
        "terrain_manifest_sha256": manifest_hash,
        "failure_map_revision": revision,
        "recorded_cells_by_source": {key: len(value) for key, value in by_source.items()},
        "recorded_failure": recorded,
        "static_terrain_only": _route(grid, grid.raw_blocked, start, goal),
        "without_recorded_lidar_cells": _route(grid, raw_without("lidar"), start, goal),
        "without_recorded_ground_truth_cells": _route(grid, raw_without("ground_truth"), start, goal),
        "limits": "Offline counterfactuals only. They do not prove obstacles false or routes safe. "
                  "They assume the current planner code, limits and terrain match the recorded run.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    parser.add_argument("--mission")
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        with args.export.open(encoding="utf-8-sig") as handle:
            export = json.load(handle)
        result = analyze(export, TerrainMap.from_bundle(args.manifest), args.mission)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        print("MARS_MAP_REPLAY:", json.dumps({"status": "unavailable", "reason": str(error)}, ensure_ascii=False))
        return 1
    print("MARS_MAP_REPLAY:", json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
