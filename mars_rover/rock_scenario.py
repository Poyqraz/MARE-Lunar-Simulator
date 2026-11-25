"""Reproducible SYNTHETIC rock layouts sized from the reference rover, for pipeline tests.

These rocks are procedural test obstacles, not measured Mars objects. Positions are
local ROS metres (x east, y north) on a prepared bundle; sizes are multiples of the
rover's own geometry so every rock's purpose is traceable:

    python -m mars_rover.rock_scenario --manifest generated/belva-lab-20261125/manifest.json \
        --start 180 300 --heading-deg 0 --output Saved/Mars/belva-rocks-01.json
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random

import numpy as np

# Unreal Leo_Raph Blueprint, read in the editor on 2026-11-25 (component bounds and collision).
ROVER = {
    "source": "/Game/Blueprints/Leo_Raph (editor read 2026-11-25)",
    "wheel_radius_m": 0.0886,     # sphere collision radius of Raph_Rover_Wheel_Common
    "wheel_width_m": 0.0836,      # wheel mesh width
    "track_m": 0.38,              # left/right wheel centre spacing
    "wheelbase_m": 0.39,          # front/rear wheel centre spacing
    "belly_clearance_m": 0.089,   # wheel bottom to body collision box bottom
}
# (name, exposed height as a multiple of a rover quantity, purpose)
CLASSES = (
    ("pebble", ("wheel_radius_m", 0.5), "below the 0.15 m obstacle threshold: expected traversable"),
    ("belly", ("belly_clearance_m", 1.0), "about belly clearance: expected below threshold, wheel climbs it"),
    ("threshold", ("wheel_radius_m", 1.7), "just over the 0.15 m map obstacle threshold"),
    ("blocker", ("wheel_radius_m", 3.4), "clearly blocking: about 2x the threshold"),
)


def _rotation(heading_deg):
    h = math.radians(heading_deg)
    return np.array([[math.cos(h), -math.sin(h)], [math.sin(h), math.cos(h)]])


def generate(heights, resolution_m, start_cell, heading_deg, *, seed=20261125, max_slope_deg=6.0):
    """Detour target ahead of the start, plus one rock of each size class off to the left.

    Raises if a rock would sit on terrain steeper than max_slope_deg, so a size class is never
    confused with the slope it stands on.
    """
    rng = random.Random(seed)
    rows, cols = heights.shape
    start = np.array([start_cell[0] * resolution_m, start_cell[1] * resolution_m])
    rot = _rotation(heading_deg)
    gy, gx = np.gradient(heights, resolution_m)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    layout = [("detour_blocker", "blocker", (6.0, 0.0))]
    layout += [(f"row_{name}", name, (4.0 + 2.5 * i, 3.0)) for i, (name, _, _) in enumerate(CLASSES)]
    rocks = []
    for rock_id, cls, (ahead, left) in layout:
        _, (quantity, factor), purpose = next(c for c in CLASSES if c[0] == cls)
        exposed = round(ROVER[quantity] * factor, 4)
        jitter = np.array([rng.uniform(-0.2, 0.2), rng.uniform(-0.2, 0.2)])
        xy = start + rot @ (np.array([ahead, left]) + jitter)
        col, row = int(round(xy[0] / resolution_m)), int(round(xy[1] / resolution_m))
        if not (1 <= col < cols - 1 and 1 <= row < rows - 1):
            raise ValueError(f"{rock_id} falls outside the terrain")
        local_slope = float(slope[row - 1:row + 2, col - 1:col + 2].max())
        if local_slope > max_slope_deg:
            raise ValueError(f"{rock_id} would sit on {local_slope:.1f} deg terrain; choose another start")
        # Ellipsoid: footprint 1.6x-2.2x the exposed height, buried 30% so it cannot roll.
        width, length = exposed * rng.uniform(1.6, 2.2), exposed * rng.uniform(1.6, 2.2)
        rocks.append({
            "id": rock_id, "class": cls, "purpose": purpose,
            "size_rule": f"exposed height = {factor} x rover {quantity}",
            "center_xy_m": [round(float(xy[0]), 4), round(float(xy[1]), 4)],
            "terrain_z_m": round(float(heights[row, col]), 4), "terrain_slope_deg": round(local_slope, 2),
            "exposed_height_m": exposed, "burial_fraction": 0.3,
            "size_m": [round(width, 4), round(length, 4), round(exposed / 0.7, 4)],
            "yaw_deg": round(rng.uniform(0, 180), 2),
        })
    goal = start + rot @ np.array([12.0, 0.0])
    return {"schema_version": 1, "kind": "synthetic_rock_test",
            "notice": "Procedural test obstacles for pipeline validation. NOT measured Mars rocks.",
            "seed": seed, "rover": ROVER, "start_cell": list(start_cell), "heading_deg": heading_deg,
            "detour_goal_xy_m": [round(float(goal[0]), 4), round(float(goal[1]), 4)], "rocks": rocks}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--start", nargs=2, type=int, required=True, metavar=("COL", "ROW"))
    parser.add_argument("--heading-deg", type=float, default=0.0, help="ROS heading: 0 = east, 90 = north")
    parser.add_argument("--seed", type=int, default=20261125)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error(f"Output exists: {args.output}; choose a new file")
    heights = np.loadtxt(args.manifest.parent / "elevation.csv")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    scenario = generate(heights, manifest["grid"]["resolution_m"], tuple(args.start), args.heading_deg, seed=args.seed)
    scenario["manifest_sha256"] = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(scenario, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.output} ({len(scenario['rocks'])} synthetic rocks; not measured Mars objects)")


if __name__ == "__main__":
    main()
