"""Metric terrain A*: measured relief is retained, unknown posts stay blocked.

    python -m mars_rover.planning --start 126 126 --goal 200 100 --output generated/route.json

Limits describe a simulation experiment, not a certified physical rover.
Standard A* and geometric tests are implemented here; no starred source is vendored.
"""

import argparse
from dataclasses import asdict, dataclass
import hashlib
import heapq
import importlib.util
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


class NoRoute(ValueError):
    pass


@dataclass(frozen=True)
class PlanningLimits:
    robot_radius_m: float = 0.6
    max_slope_deg: float = 15.0
    max_neighbor_step_m: float = 0.35
    obstacle_height_m: float = 0.15
    slope_cost_weight: float = 2.0

    def __post_init__(self):
        if any(type(v) not in (float, int) or not math.isfinite(v) for v in asdict(self).values()):
            raise ValueError("Planning limits must be finite numbers")
        if (
            self.robot_radius_m < 0
            or not 0 < self.max_slope_deg < 90
            or min(self.max_neighbor_step_m, self.obstacle_height_m) <= 0
            or self.slope_cost_weight < 0
        ):
            raise ValueError("Invalid terrain/vehicle limits")


class TerrainMap:
    def __init__(self, heights, resolution_m, limits=None, *, valid=None):
        self.heights = np.asarray(heights, dtype="float64").copy()
        if (
            self.heights.ndim != 2
            or min(self.heights.shape) < 3
            or not math.isfinite(resolution_m)
            or resolution_m <= 0
        ):
            raise ValueError("Use a 2D height grid and positive metre resolution")
        self.resolution_m, self.limits = float(resolution_m), limits or PlanningLimits()
        self.manifest = None
        self.manifest_sha256 = None
        finite = np.isfinite(self.heights)
        if valid is not None:
            if np.shape(valid) != finite.shape:
                raise ValueError("Validity mask must match height grid")
            finite &= np.asarray(valid, dtype=bool)
        a, b, c, d = self.heights[:-1, :-1], self.heights[:-1, 1:], self.heights[1:, :-1], self.heights[1:, 1:]
        with np.errstate(invalid="ignore"):
            quad_slope = np.maximum.reduce(
                [
                    np.degrees(np.arctan(np.hypot(dx, dy) / resolution_m))
                    for dx, dy in ((b - a, c - a), (d - c, d - b), (b - a, d - b), (d - c, c - a))
                ]
            )
            quad_step = np.maximum.reduce([np.abs(b - a), np.abs(c - a), np.abs(d - b), np.abs(d - c)])
        quad_slope = np.nan_to_num(quad_slope, nan=np.inf)
        quad_step = np.nan_to_num(quad_step, nan=np.inf)
        self.slope_deg, step = np.zeros_like(self.heights), np.zeros_like(self.heights)
        for dr, dc in ((0, 0), (0, 1), (1, 0), (1, 1)):
            target = np.s_[dr : dr + quad_slope.shape[0], dc : dc + quad_slope.shape[1]]
            self.slope_deg[target] = np.maximum(self.slope_deg[target], quad_slope)
            step[target] = np.maximum(step[target], quad_step)
        self.raw_blocked = (
            ~finite | (self.slope_deg > self.limits.max_slope_deg) | (step > self.limits.max_neighbor_step_m)
        )
        self.raw_blocked[[0, -1], :] = True
        self.raw_blocked[:, [0, -1]] = True
        self.blocked = self._inflate(self.raw_blocked)
        self.revision = 0

    @classmethod
    def from_bundle(cls, path=None, *, limits=None):
        path = Path(path) if path else ROOT / "Content/Mars/Jezero/manifest.json"
        spec = importlib.util.spec_from_file_location("mars_planning_bundle", ROOT / "Content/Python/mars_setup.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        manifest, _ = module.load_bundle(path)
        layout, grid = manifest["landscape"], manifest["grid"]
        raw = np.fromfile(path.parent / "heightmap.r16", dtype="<u2").reshape(layout["height"], layout["width"])
        heights = np.fliplr(raw).astype(float)[: grid["height"], : grid["width"]] * manifest["vertical_quantization_m"]
        result = cls(heights, grid["resolution_m"], limits, valid=np.loadtxt(path.parent / "soil.csv") > 0)
        result.manifest, result.manifest_sha256 = manifest, hashlib.sha256(path.read_bytes()).hexdigest()
        result.bundle_path = path.parent.resolve()
        return result

    def _inflate(self, raw):
        if self.limits.robot_radius_m == 0:
            return raw.copy()
        # A blocked post represents a square raster footprint, not a point.
        radius = self.limits.robot_radius_m / self.resolution_m + math.sqrt(2) / 2
        cells = math.ceil(radius)
        if cells > 128:
            raise ValueError("Footprint inflation exceeds the supported local grid budget")
        result = raw.copy()
        h, w = raw.shape
        for dy in range(-cells, cells + 1):
            for dx in range(-cells, cells + 1):
                if math.hypot(dx, dy) > radius:
                    continue
                y0, y1, x0, x1 = max(0, dy), min(h, h + dy), max(0, dx), min(w, w + dx)
                if y1 > y0 and x1 > x0:
                    result[y0:y1, x0:x1] |= raw[y0 - dy : y1 - dy, x0 - dx : x1 - dx]
        return result

    def cell(self, xy):
        if len(xy) != 2 or not all(type(v) in (float, int) and math.isfinite(v) for v in xy):
            raise ValueError("Goal/start must contain two finite metre coordinates")
        x, y = xy
        h, w = self.heights.shape
        if not 0 <= x <= (w - 1) * self.resolution_m or not 0 <= y <= (h - 1) * self.resolution_m:
            raise ValueError("Goal/start lies outside measured terrain")
        return int(math.floor(y / self.resolution_m + 0.5)), int(math.floor(x / self.resolution_m + 0.5))

    def segment_clear(self, a, b):
        try:
            count = max(1, math.ceil(math.dist(a, b) / (self.resolution_m / 4)))
            previous = None
            for t in np.linspace(0, 1, count + 1):
                row, col = self.cell((float(a[0] + t * (b[0] - a[0])), float(a[1] + t * (b[1] - a[1]))))
                if self.blocked[row, col]:
                    return False
                if previous and row != previous[0] and col != previous[1]:
                    if self.blocked[row, previous[1]] or self.blocked[previous[0], col]:
                        return False
                previous = row, col
            return True
        except ValueError:
            return False

    def plan(self, start, goal, *, max_expansions=1_000_000):
        start, goal = tuple(map(float, start)), tuple(map(float, goal))
        first, last = self.cell(start), self.cell(goal)
        if self.blocked[first] or self.blocked[last]:
            raise NoRoute("Start/goal is blocked after terrain and vehicle-footprint checks")
        costs, parent, queue = {first: 0.0}, {}, [(0.0, 0.0, first)]
        expanded = 0
        r = self.resolution_m
        while queue:
            _, cost, current = heapq.heappop(queue)
            if cost > costs[current]:
                continue
            if current == last:
                cells = [last]
                while cells[-1] != first:
                    cells.append(parent[cells[-1]])
                route = [(col * r, row * r) for row, col in reversed(cells)]
                route = [start, *route, goal]
                route = [p for i, p in enumerate(route) if i == 0 or p != route[i - 1]]
                if not all(self.segment_clear(a, b) for a, b in zip(route, route[1:])):
                    raise NoRoute("Exact start/goal connection intersects a blocked cell")
                return route
            expanded += 1
            if expanded > max_expansions:
                raise NoRoute("Planning expansion budget exceeded")
            row, col = current
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
                nr, nc = row + dy, col + dx
                if not (0 <= nr < self.heights.shape[0] and 0 <= nc < self.heights.shape[1]) or self.blocked[nr, nc]:
                    continue
                if dx and dy and (self.blocked[row, nc] or self.blocked[nr, col]):
                    continue
                distance = math.sqrt(
                    (r * dx) ** 2 + (r * dy) ** 2 + (self.heights[nr, nc] - self.heights[current]) ** 2
                )
                weight = (
                    1
                    + self.limits.slope_cost_weight
                    * (max(self.slope_deg[current], self.slope_deg[nr, nc]) / self.limits.max_slope_deg) ** 2
                )
                candidate = cost + distance * weight
                neighbour = nr, nc
                if candidate < costs.get(neighbour, math.inf):
                    costs[neighbour], parent[neighbour] = candidate, current
                    heuristic = math.hypot(nr - last[0], nc - last[1]) * r
                    heapq.heappush(queue, (candidate + heuristic, candidate, neighbour))
        raise NoRoute("No connected traversable route to the requested goal")

    def surface_height(self, xy):
        x, y = xy
        self.cell((float(x), float(y)))
        c, r = x / self.resolution_m, y / self.resolution_m
        i, j = min(int(r), self.heights.shape[0] - 2), min(int(c), self.heights.shape[1] - 2)
        dy, dx = r - i, c - j
        return float(
            (1 - dy) * ((1 - dx) * self.heights[i, j] + dx * self.heights[i, j + 1])
            + dy * ((1 - dx) * self.heights[i + 1, j] + dx * self.heights[i + 1, j + 1])
        )

    def observe(self, points):
        points = np.asarray(points, dtype=float)
        if points.ndim != 2 or points.shape[1] != 3:
            raise ValueError("Observed points must be Nx3 local-map metres")
        h, w = self.heights.shape
        points = points[
            np.isfinite(points).all(axis=1)
            & (points[:, 0] >= 0)
            & (points[:, 1] >= 0)
            & (points[:, 0] <= (w - 1) * self.resolution_m)
            & (points[:, 1] <= (h - 1) * self.resolution_m)
        ]
        c, r = points[:, 0] / self.resolution_m, points[:, 1] / self.resolution_m
        i, j = np.minimum(r.astype(int), h - 2), np.minimum(c.astype(int), w - 2)
        dy, dx = r - i, c - j
        heights = (1 - dy) * ((1 - dx) * self.heights[i, j] + dx * self.heights[i, j + 1]) + dy * (
            (1 - dx) * self.heights[i + 1, j] + dx * self.heights[i + 1, j + 1]
        )
        residual = points[:, 2] - heights
        positive = int(np.sum(residual > self.limits.obstacle_height_m))
        negative = int(np.sum(residual < -self.limits.obstacle_height_m))
        hazard = np.isfinite(residual) & (np.abs(residual) > self.limits.obstacle_height_m)
        rows, cols = np.floor(r[hazard] + 0.5).astype(int), np.floor(c[hazard] + 0.5).astype(int)
        changed = bool(np.any(~self.raw_blocked[rows, cols]))
        self.raw_blocked[rows, cols] = True
        if changed:
            self.blocked = self._inflate(self.raw_blocked)
            self.revision += 1
        return {
            "positive_obstacles": positive,
            "negative_obstacles": negative,
            "valid_inside_points": int(np.isfinite(residual).sum()),
            "map_changed": bool(changed),
            "unknown_is_free": False,
            "micro_geometry_complete": False,
        }

    def geographic_goal(self, longitude, latitude):
        if self.manifest is None or not (-180 <= longitude <= 360 and -90 <= latitude <= 90):
            raise ValueError("Geographic goals require a Mars bundle and valid longitude/latitude")
        from pyproj import CRS, Transformer

        crs = CRS.from_wkt(self.manifest["grid"]["crs_wkt"])
        x, y = Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True).transform(longitude, latitude)
        origin = self.manifest["grid"]["projected_origin_m"]
        goal = float(x - origin[0]), float(y - origin[1])
        self.cell(goal)
        return goal


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "Content/Mars/Jezero/manifest.json")
    parser.add_argument("--start", type=float, nargs=2, required=True)
    parser.add_argument("--goal", type=float, nargs=2, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        grid = TerrainMap.from_bundle(args.manifest)
        route = grid.plan(args.start, args.goal)
        report = {
            "schema_version": 1,
            "manifest_sha256": grid.manifest_sha256,
            "limits": asdict(grid.limits),
            "frame": "local east/north/up, metres",
            "waypoints_local_m": [[x, y, grid.surface_height((x, y))] for x, y in route],
            "length_xy_m": sum(math.dist(a, b) for a, b in zip(route, route[1:])),
            "native_rover_verified": False,
            "terrain_source": "measured DEM prior",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write("\n")
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
    print(f"Planned {len(route)} waypoints: {args.output}")


if __name__ == "__main__":
    main()
