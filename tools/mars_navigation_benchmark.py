"""Reproduce offline route/kinematic checks on the bundled measured Jezero crop.

Run from the repository root:
    python tools/mars_navigation_benchmark.py --output generated/navigation.json
Optional --figure needs requirements-mars-plot.txt. Neither result is an UE run.
"""

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mars_rover.navigation import RouteFollower  # noqa: E402
from mars_rover.planning import NoRoute, TerrainMap  # noqa: E402


def benchmark(grid):
    cases, paths = [], []
    start = (126.0, 126.0)
    for goal in ((200.0, 100.0), (60.0, 100.0), (180.0, 180.0), (100.0, 200.0)):
        route = grid.plan(start, goal)
        if not all(grid.segment_clear(a, b) for a, b in zip(route, route[1:])):
            raise RuntimeError("A planned segment crosses the inflated blocked mask")
        follower = RouteFollower(route)
        x, y, yaw = *start, 0.0
        steps = 0
        # Deliberately a planar, no-slip kinematic check. It is not a wheel,
        # collision, terrain contact, sensor or Unreal simulation.
        for steps in range(1, 120_001):
            v, w = follower.command((x, y, yaw))
            old = x, y
            x += v * math.cos(yaw) * 0.05
            y += v * math.sin(yaw) * 0.05
            yaw += w * 0.05
            if not grid.segment_clear(old, (x, y)):
                raise RuntimeError("Kinematic tracker leaves the traversable corridor")
            if follower.arrived:
                break
        if not follower.arrived or follower.command((x, y, yaw)) != (0, 0):
            raise RuntimeError("Kinematic tracker failed to arrive and stop")
        path = np.array(route)
        rows, cols = (
            np.floor(path[:, 1] / grid.resolution_m + 0.5).astype(int),
            np.floor(path[:, 0] / grid.resolution_m + 0.5).astype(int),
        )
        cases.append(
            {
                "start_local_m": list(start),
                "goal_local_m": list(goal),
                "waypoint_count": len(route),
                "route_length_xy_m": sum(math.dist(a, b) for a, b in zip(route, route[1:])),
                "max_quad_slope_bound_on_route_deg": float(grid.slope_deg[rows, cols].max()),
                "all_segments_clear": True,
                "kinematic_arrived_and_stopped": True,
                "kinematic_final_distance_m": math.dist((x, y), goal),
                "kinematic_duration_s": steps * 0.05,
            }
        )
        paths.append(route)
    rejected = []
    for goal in ((-1.0, 20.0), (0.0, 0.0)):
        try:
            grid.plan(start, goal)
        except (NoRoute, ValueError) as error:
            rejected.append({"goal_local_m": list(goal), "reason": str(error)})
        else:
            raise RuntimeError("Invalid goal accepted")
    report = {
        "schema_version": 1,
        "manifest_sha256": grid.manifest_sha256,
        "frame": "local east/north/up, metres",
        "terrain_source": "decoded r16 of the measured USGS Jezero_C DTM crop",
        "grid_shape": list(grid.heights.shape),
        "grid_resolution_m": grid.resolution_m,
        "limits": asdict(grid.limits),
        "inflated_blocked_posts": int(grid.blocked.sum()),
        "successful_routes": cases,
        "rejected_goals": rejected,
        "kinematic_model": {"dt_s": 0.05, "speed_m_s": 0.15, "slip": "not modelled", "pose": "exact"},
        "native_unreal_executed": False,
        "native_sensor_stream_verified": False,
        "native_rover_verified": False,
        "micro_geometry_complete": False,
        "scientific_dem_accuracy_verified": False,
    }
    return report, paths


def figure(grid, paths, output):
    import matplotlib.pyplot as plt

    h, w = grid.heights.shape
    extent = [-0.5, w - 0.5, -0.5, h - 0.5]
    extent = [v * grid.resolution_m for v in extent]
    fig, ax = plt.subplots(figsize=(9.4, 8), constrained_layout=True)
    image = ax.imshow(grid.heights, origin="lower", extent=extent, cmap="terrain")
    mask = np.ma.masked_where(~grid.blocked, grid.blocked)
    ax.imshow(mask, origin="lower", extent=extent, cmap="Reds", vmin=0, vmax=1, alpha=0.45, interpolation="nearest")
    for index, route in enumerate(paths, 1):
        a = np.array(route)
        ax.plot(a[:, 0], a[:, 1], linewidth=2, label=f"Route {index}")
        ax.scatter(*a[-1], marker="x", s=65, color="black")
    ax.scatter(126, 126, s=55, color="white", edgecolors="black", label="Start")
    ax.set(xlabel="Local east (m)", ylabel="Local north (m)", xlim=(0, 252), ylim=(0, 252))
    ax.set_title(
        "Measured Jezero crop: offline geometric route checks\nRed: inflated blocked mask; not an Unreal render"
    )
    ax.legend(loc="lower right")
    fig.colorbar(image, ax=ax, label="Height above removed local datum (m)")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as handle:
        fig.savefig(handle, format="png", dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--figure", type=Path)
    args = parser.parse_args()
    if args.output.exists() or (args.figure and args.figure.exists()):
        parser.error("Choose new output paths")
    grid = TerrainMap.from_bundle()
    report, paths = benchmark(grid)
    if args.figure:
        figure(grid, paths, args.figure)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write("\n")
    print(f"PASS: {len(paths)} routes, kinematic arrival/stop, and invalid-goal rejection. No native UE execution.")


if __name__ == "__main__":
    main()
