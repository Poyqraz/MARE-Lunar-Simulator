"""Reconstruct a recorded Mars navigation map offline without commanding the rover.

Counterfactual maps are evidence about the recorded planner inputs, not evidence
that any obstacle is false or that a route is safe to drive.
"""

import argparse
import copy
import json
from pathlib import Path
import sys

import numpy as np

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


def _representative_lidar_summary(frames):
    """Describe selected first points without treating them as a whole scan."""
    values, point_counts = [], []
    expected = 0
    for frame in frames:
        if frame.get("source") != "lidar":
            continue
        for item in frame["new_cells"]:
            expected += 1
            residual = item.get("sample_residual_m")
            count = item.get("hazard_points")
            if type(residual) in (float, int) and np.isfinite(residual):
                values.append(float(residual))
            if type(count) is int and count > 0:
                point_counts.append(count)
    return {
        "recorded_lidar_cells": expected, "samples_with_residual": len(values),
        "positive_samples": sum(v > 0 for v in values), "negative_samples": sum(v < 0 for v in values),
        "min_residual_m": min(values) if values else None,
        "median_residual_m": float(np.median(values)) if values else None,
        "max_residual_m": max(values) if values else None,
        "cells_with_hazard_point_counts": len(point_counts),
        "cells_with_one_hazard_point": sum(v == 1 for v in point_counts),
        "limits": "One selected sample per newly occupied cell, chosen after crossing the threshold; "
                  "not a representative sample of the full scan or proof of an obstacle.",
    }


def _render_image(path, grid, by_source, raw, mission, start, goal):
    """Save a labelled, exclusive-create image of the reconstructed grid."""
    from PIL import Image, ImageDraw

    h, w = grid.heights.shape
    if h * w > 2_000_000:
        raise ValueError("Replay image exceeds the display budget")
    values = grid.heights
    finite = np.isfinite(values)
    normalized = np.zeros_like(values)
    if finite.any():
        lo, hi = float(values[finite].min()), float(values[finite].max())
        normalized[finite] = (values[finite] - lo) / max(hi - lo, 1e-9)
    base = np.stack([42 + normalized * 68, 56 + normalized * 98, 43 + normalized * 58], axis=-1)
    base[~finite] = 0
    base = np.asarray(np.flipud(base), dtype=np.uint8)
    base_image = Image.fromarray(base, "RGB").convert("RGBA")

    classes = np.zeros((h, w), dtype=np.uint8)
    classes[grid._inflate(raw)] = 6
    classes[raw] = 1
    for label, code in (("lidar", 2), ("ground_truth", 3), ("stereo", 4)):
        for row, col in by_source[label]:
            classes[row, col] = code
    colors = np.array([[0, 0, 0, 0], [239, 102, 115, 175], [255, 209, 102, 220],
                       [252, 129, 199, 220], [190, 140, 255, 220], [245, 245, 245, 220],
                       [174, 134, 232, 100]], dtype=np.uint8)
    image = Image.alpha_composite(base_image, Image.fromarray(np.flipud(colors[classes]), "RGBA"))
    scale = min(4, max(1, 1200 // max(w, h)))
    image = image.resize((w * scale, h * scale), Image.Resampling.NEAREST).convert("RGB")
    canvas = Image.new("RGB", (w * scale, h * scale + 122), (18, 25, 35))
    canvas.paste(image, (0, 0))
    draw = ImageDraw.Draw(canvas)

    def pixel(xy):
        x, y = map(float, xy)
        return (round(x / grid.resolution_m / (w - 1) * (w * scale - 1)),
                round((1 - y / grid.resolution_m / (h - 1)) * (h * scale - 1)))

    for name, color in (("initial_plan", "#ff6b7d"), ("active_plan", "#ffa94d")):
        route = mission.get(name) or []
        if len(route) >= 2:
            draw.line([pixel(point) for point in route], fill=color, width=max(2, scale))
    for xy, color in ((start, "#59b0ff"), (goal, "#ffbe5c")):
        x, y = pixel(xy)
        r = max(4, scale * 2)
        draw.ellipse((x - r, y - r, x + r, y + r), outline=color, width=max(2, scale // 2))
    text_y = h * scale + 7
    lines = [
        "RECONSTRUCTED FAILURE GRID - NORTH UP - offline, not a live view",
        "Red: terrain restriction | Yellow: LiDAR first | Pink: ground truth depth first",
        "Purple: stereo first | Translucent violet: planner footprint margin",
        "Pink/orange lines: saved plans | Blue ring: failure position | Orange ring: goal",
        "First source is not proof of a real obstacle. Unblocked is not verified safe.",
        "Planner code, limits and terrain are assumed to match the recorded run.",
    ]
    for number, text in enumerate(lines):
        draw.text((8, text_y + 17 * number), text, fill="white")
    with Path(path).open("xb") as handle:
        canvas.save(handle, format="PNG")


def analyze(export, grid, mission_id=None, *, image_path=None):
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
    result = {
        "status": "reconstructed",
        "mission_id": selected,
        "terrain_manifest_sha256": manifest_hash,
        "failure_map_revision": revision,
        "recorded_cells_by_source": {key: len(value) for key, value in by_source.items()},
        "recorded_failure": recorded,
        "static_terrain_only": _route(grid, grid.raw_blocked, start, goal),
        "without_recorded_lidar_cells": _route(grid, raw_without("lidar"), start, goal),
        "without_recorded_ground_truth_cells": _route(grid, raw_without("ground_truth"), start, goal),
        "selected_lidar_samples": _representative_lidar_summary(selected_frames),
        "limits": "Offline counterfactuals only. They do not prove obstacles false or routes safe. "
                  "They assume the current planner code, limits and terrain match the recorded run.",
    }
    if image_path is not None:
        try:
            _render_image(image_path, grid, by_source, raw_without(None), mission, start, goal)
            result["image_path"] = str(image_path)
        except (ImportError, OSError, ValueError, TypeError) as error:
            result["image_error"] = str(error)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    parser.add_argument("--mission")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--image", type=Path, help="write a new PNG of the reconstructed map; never overwrites")
    args = parser.parse_args(argv)
    try:
        with args.export.open(encoding="utf-8-sig") as handle:
            export = json.load(handle)
        result = analyze(export, TerrainMap.from_bundle(args.manifest), args.mission, image_path=args.image)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        print("MARS_MAP_REPLAY:", json.dumps({"status": "unavailable", "reason": str(error)}, ensure_ascii=False))
        return 1
    print("MARS_MAP_REPLAY:", json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
