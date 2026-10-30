"""Read-only, bounded viewer taps for MARE's existing simulator streams.

The planner receives full frames. The viewer retains a small latest-frame
history and reduces data only for display; it never opens a second sensor port.
"""

from collections import deque
import io
import math
import threading
import time

import numpy as np

try:
    from PIL import Image
except ImportError:  # Navigation must remain usable without the optional viewer encoder.
    Image = None

from .sensors import depth_points, transform_matrix


def local_depth_view(grid, world_from_body, body_from_camera, hfov_deg, depth_m, *, stride=6):
    """Visualize sampled, capture-time ground-truth depth, retaining unknown cells.

    Heights are relative to the DEM beneath the rover. This display does not
    change the full-resolution navigation grid or classify terrain as safe.
    """
    world_from_body = transform_matrix(world_from_body)
    body_from_camera = transform_matrix(body_from_camera)
    points = depth_points(depth_m, hfov_deg=hfov_deg, stride=stride)
    points = points[points[:, 2] <= 8.0]
    matrix = world_from_body @ body_from_camera
    world = points @ matrix[:3, :3].T + matrix[:3, 3]
    x0, y0 = world_from_body[:2, 3]
    reference = grid.surface_height((float(x0), float(y0)))
    if not math.isfinite(reference):
        raise ValueError("DEM ground reference is unknown")
    yaw = math.atan2(world_from_body[1, 0], world_from_body[0, 0])
    co, si = math.cos(yaw), math.sin(yaw)
    delta = world[:, :2] - np.array([x0, y0])
    right = si * delta[:, 0] - co * delta[:, 1]
    forward = co * delta[:, 0] + si * delta[:, 1]
    res, width, height = 0.25, 33, 32
    columns = np.floor(right / res + (width - 1) / 2 + 0.5).astype(int)
    rows = np.floor(forward / res).astype(int)
    valid = (rows >= 0) & (rows < height) & (columns >= 0) & (columns < width) & np.isfinite(world[:, 2])
    cells = np.full(height * width, -np.inf)
    np.maximum.at(cells, rows[valid] * width + columns[valid], world[valid, 2] - reference)
    known = np.isfinite(cells)

    def gradient(dx, dy):
        try:
            value = grid.surface_height((float(x0 + dx), float(y0 + dy)))
            return float(value - reference) if math.isfinite(value) else 0.0
        except ValueError:
            return 0.0

    return {"w": width, "h": height, "res": res,
            "z": [int(round(v * 100)) if k else None for v, k in zip(cells, known)],
            "plane": [gradient(si, -co), gradient(co, si), 0.0],
            "observed": float(known.mean()), "display_only": True, "source": "unreal_ground_truth_depth"}


def project_route(grid, world_from_body, body_from_camera, hfov_deg, width, height, route, *, width_m=0.65):
    """Project a DEM-backed route into a captured optical camera frame.

    Camera axes are x right, y down, z forward. Width is an illustrative
    reference-rover assumption, not a validated footprint or clearance.
    """
    world_from_body = transform_matrix(world_from_body)
    body_from_camera = transform_matrix(body_from_camera)
    if (not 0 < hfov_deg < 180 or type(width) is not int or type(height) is not int
            or width < 1 or height < 1 or not 0 < width_m <= 5 or len(route) < 2):
        raise ValueError("Invalid route projection settings")
    points = [tuple(map(float, xy)) for xy in route]
    for xy in points:
        grid.cell(xy)
    camera_from_world = np.linalg.inv(world_from_body @ body_from_camera)
    fx = width / (2 * math.tan(math.radians(hfov_deg) / 2))

    def project(xy, dz=0.0):
        try:
            z = grid.surface_height(xy) + dz
            if not math.isfinite(z):
                return None
            optical = camera_from_world @ np.array([xy[0], xy[1], z, 1.0])
            if optical[2] <= 0.05 or not np.isfinite(optical).all():
                return None
            return [float(0.5 + fx * optical[0] / optical[2] / width),
                    float(0.5 + fx * optical[1] / optical[2] / height)]
        except ValueError:
            return None

    samples, distance = [], 0.0
    for a, b in zip(points, points[1:]):
        length = math.dist(a, b)
        if length <= 1e-9:
            continue
        dx, dy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        n = max(1, math.ceil(length / 0.5))
        for k in range(0 if not samples else 1, n + 1):
            d = distance + length * k / n
            if d > 30 or len(samples) >= 200:
                break
            xy = (a[0] + dx * length * k / n, a[1] + dy * length * k / n)
            left = (xy[0] - dy * width_m / 2, xy[1] + dx * width_m / 2)
            right = (xy[0] + dy * width_m / 2, xy[1] - dx * width_m / 2)
            samples.append((project(xy), project(left), project(right), d))
        distance += length
        if distance >= 30 or len(samples) >= 200:
            break
    if not samples:
        raise ValueError("No nonzero route segment to display")
    destination = points[-1]
    relative = np.linalg.inv(world_from_body) @ np.array(
        [destination[0], destination[1], grid.surface_height(destination), 1.0]
    )
    return {"center": [s[0] for s in samples], "left": [s[1] for s in samples],
            "right": [s[2] for s in samples], "dist": [s[3] for s in samples],
            "goal": {"base": project(destination), "top": project(destination, 0.5),
                     "bearing": math.degrees(math.atan2(relative[1], relative[0])),
                     "dist": math.hypot(relative[0], relative[1])},
            "source": f"planned route projected on DEM; {width_m:g} m reference width assumed"}


class ViewportLink:
    """Track the editor's existing rover_cameras.py polling protocol."""

    def __init__(self, *, clock=time.monotonic):
        self.clock, self.lock = clock, threading.Lock()
        self.mode, self.applied, self.rover, self.last_seen = "follow", "idle", "none", None

    def update_editor(self, applied, rover):
        if applied not in ("idle", "follow", "orbit", "top") or not isinstance(rover, str) or len(rover) > 128:
            raise ValueError("Invalid editor viewport state")
        with self.lock:
            self.applied, self.rover, self.last_seen = applied, rover, self.clock()
            return {"mode": self.mode}

    def set_mode(self, mode):
        if mode not in ("follow", "orbit", "top"):
            raise ValueError("Unsupported viewport mode")
        with self.lock:
            self.mode = mode
        return self.status()

    def status(self):
        with self.lock:
            seen = self.last_seen
            return {"mode": self.mode, "applied": self.applied, "rover": self.rover,
                    "linked": seen is not None and 0 <= self.clock() - seen <= 2.0}


class LiveFeeds:
    def __init__(self, config, *, clock=time.monotonic, max_age_s=1.5, max_points=5000):
        self.clock, self.max_age_s, self.max_points = clock, max_age_s, max_points
        depth = config["depth"]
        center = depth.get("color_camera_id", 0)
        self.center_id_source = "measured" if "color_camera_id" in depth else "assumed_plugin_default"
        self.ids = {(depth["camera_id"], 2): "depth_gt"}
        stereo = config.get("stereo", {})
        left, right = stereo.get("left_id"), stereo.get("right_id")
        if center not in (left, right):
            self.ids[(center, 1)] = "cam_central"
        if type(left) is int and left != right:
            self.ids[(left, 1)] = "cam_left"
        if type(right) is int and left != right:
            self.ids[(right, 1)] = "cam_right"
        self.lidar_id = config["lidar"]["sensor_id"]
        self.to_body = transform_matrix(config["lidar"]["to_body"])
        self.lock = threading.Lock()
        self.frames, self.cache, self.scan = {}, {}, None
        self.frame_history = {"cam_central": deque(maxlen=3), "depth_gt": deque(maxlen=3)}
        self.camera_generation = self.lidar_generation = 0

    def camera(self, frame):
        name = self.ids.get((frame.camera_id, frame.format))
        if name is None or frame.stamp_ns is None or not self.lock.acquire(blocking=False):
            return
        try:
            old = self.frames.get(name)
            if old is None or frame.stamp_ns >= old[0].stamp_ns:
                record = (frame, self.clock())
                self.frames[name] = record
                if name in self.frame_history and (old is None or frame.stamp_ns > old[0].stamp_ns):
                    self.frame_history[name].append(record)
        finally:
            self.lock.release()

    def lidar(self, scan):
        if scan.sensor_id != self.lidar_id or not self.lock.acquire(blocking=False):
            return
        try:
            if self.scan is None or scan.stamp_ns >= self.scan[0].stamp_ns:
                self.scan = (scan, self.clock())
        finally:
            self.lock.release()

    def clear_camera(self):
        with self.lock:
            self.camera_generation += 1
            self.frames.clear()
            for history in self.frame_history.values():
                history.clear()
            self.cache.clear()

    def clear_lidar(self):
        with self.lock:
            self.lidar_generation += 1
            self.scan = None

    def _fresh(self, record):
        return record is not None and 0 <= self.clock() - record[1] <= self.max_age_s

    def status(self):
        with self.lock:
            frames, scan = dict(self.frames), self.scan
        feeds = {}
        for name, record in frames.items():
            if self._fresh(record):
                feeds[name] = {"age_s": max(0.0, self.clock() - record[1]), "stamp_ns": str(record[0].stamp_ns),
                               "source": "unreal_ground_truth_depth" if name == "depth_gt" else "unreal_rgb"}
        if self._fresh(scan):
            feeds["lidar"] = {"age_s": max(0.0, self.clock() - scan[1]),
                              "stamp_ns": str(scan[0].stamp_ns), "source": "unreal_lidar"}
        return {"feeds": feeds, "center_id_source": self.center_id_source, "image_encoder_available": Image is not None}

    def frame(self, name, stamp_ns=None):
        with self.lock:
            record = self.frames.get(name) if stamp_ns is None else next(
                (r for r in reversed(self.frame_history.get(name, ())) if r[0].stamp_ns == stamp_ns), None
            )
        return record[0] if self._fresh(record) else None

    def image(self, name, *, with_stamp=False):
        if Image is None:
            return None
        with self.lock:
            record, cached, generation = self.frames.get(name), self.cache.get(name), self.camera_generation
        if not self._fresh(record):
            return None
        frame = record[0]
        signature = (frame.camera_id, frame.frame_id, frame.stamp_ns)
        if cached and cached[0] == signature:
            data = cached[1]
        else:
            if name == "depth_gt":
                metres = frame.depth_m()
                valid = np.isfinite(metres)
                t = np.clip(np.where(valid, metres, 0) / 8.0, 0, 1)
                rgb = np.stack([np.clip(1.5 - abs(4 * t - k), 0, 1) for k in (3, 2, 1)], axis=-1)
                rgb[~valid] = 0
                pixels = np.uint8(rgb * 255)
            elif name.startswith("cam_"):
                pixels = frame.pixels[:, :, [2, 1, 0]]  # BGRA -> RGB
            else:
                return None
            buffer = io.BytesIO()
            Image.fromarray(pixels).save(buffer, "JPEG", quality=80)
            data = buffer.getvalue()
        with self.lock:
            if generation != self.camera_generation or not self._fresh(record):
                return None
            if self.frames.get(name) is record:
                self.cache[name] = (signature, data)
        return (data, str(frame.stamp_ns)) if with_stamp else data

    def lidar_view(self):
        with self.lock:
            record, generation = self.scan, self.lidar_generation
        if not self._fresh(record):
            return None
        points = record[0].points
        points = points[np.isfinite(points).all(axis=1)]
        if len(points) > self.max_points:
            points = points[np.linspace(0, len(points) - 1, self.max_points, dtype=np.int64)]
        points = points @ self.to_body[:3, :3].T + self.to_body[:3, 3]
        with self.lock:
            if generation != self.lidar_generation or not self._fresh(record):
                return None
        return {"points": np.round(points, 3).ravel().tolist(), "count": len(points), "frame": "rover",
                "stamp_ns": str(record[0].stamp_ns), "source": "unreal_lidar"}
