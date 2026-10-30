"""Read the actual Unreal LIDR/NAVF protocols without ROS.

LIDR already contains FLU metres. NAVF format 2 is planar camera-axis depth
in centimetres, not ray range and not stereo-estimated depth. Capture stamps
use the shared GncSimTime epoch. Invalid returns never become a free surface.
"""

from collections import deque
from dataclasses import dataclass
import math
import struct

import numpy as np

# LiDAR stores epoch seconds as a double; allow at most this rounding error
# when comparing it with integer-nanosecond camera and pose timestamps.
CAPTURE_CLOCK_TOLERANCE_NS = 1024
LIDAR_HEADER = struct.Struct("<4sBBHQdffIIII")
NAV_HEADER = struct.Struct("<4sBBBBHHQI")
POINT_DTYPE = np.dtype(
    [("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("intensity", "<f4"), ("ring", "<u2"), ("column", "<u2")]
)


@dataclass
class LidarScan:
    sensor_id: int
    frame_id: int
    stamp_ns: int
    points: np.ndarray
    rows: int
    columns: int


@dataclass
class CameraFrame:
    camera_id: int
    frame_id: int
    stamp_ns: int | None
    format: int
    pixels: np.ndarray

    def depth_m(self, *, stride=1):
        if self.format != 2:
            raise ValueError("Colour packets are not depth")
        if type(stride) is not int or stride < 1:
            raise ValueError("Depth sampling stride must be a positive integer")
        depth = self.pixels[::stride, ::stride].astype("float64") / 100
        depth[(~np.isfinite(depth)) | (depth <= 0) | (depth >= 1e5)] = np.nan
        return depth


class LidarStream:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        if len(data) > 64 * 1024 * 1024:
            raise ValueError("Oversize LiDAR input chunk")
        self.buffer.extend(data)
        result = []
        while len(self.buffer) >= LIDAR_HEADER.size:
            magic, version, sid, flags, frame, stamp, hfov, vfov, cols, rows, count, step = LIDAR_HEADER.unpack_from(
                self.buffer
            )
            if (
                magic != b"LIDR"
                or version != 1
                or flags != 1
                or step != 20
                or not 1 <= cols <= 4096
                or not 1 <= rows <= 512
                or count != rows * cols
                or not math.isfinite(stamp)
                or not 0 < stamp < 9_223_372_036
                or not 0 < hfov <= 360
                or not 0 < vfov <= 180
            ):
                self.buffer.clear()
                raise ValueError("Invalid/unsupported LIDR header")
            size = LIDAR_HEADER.size + count * step
            if len(self.buffer) < size:
                break
            raw = np.frombuffer(bytes(self.buffer[LIDAR_HEADER.size : size]), dtype=POINT_DTYPE)
            index = np.arange(count)
            if not np.array_equal(raw["ring"], index // cols) or not np.array_equal(raw["column"], index % cols):
                raise ValueError("LIDR organized point indices disagree with dimensions")
            points = np.column_stack((raw["x"], raw["y"], raw["z"])).astype("float64")
            points[~np.isfinite(points).all(axis=1)] = np.nan
            result.append(LidarScan(sid, frame, int(round(stamp * 1e9)), points, rows, cols))
            del self.buffer[:size]
        return result


class NavStream:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        if len(data) > 64 * 1024 * 1024:
            raise ValueError("Oversize camera input chunk")
        self.buffer.extend(data)
        result = []
        while len(self.buffer) >= NAV_HEADER.size:
            magic, version, cid, fmt, pad, w, h, frame, payload = NAV_HEADER.unpack_from(self.buffer)
            if (
                magic != b"NAVF"
                or version not in (1, 2)
                or fmt not in (1, 2)
                or pad != 0
                or not 0 < w * h <= 4_194_304
                or payload != w * h * 4
            ):
                self.buffer.clear()
                raise ValueError("Invalid/unsupported NAVF header or payload budget")
            header_size = 32 if version == 2 else 24
            size = header_size + payload
            if len(self.buffer) < size:
                break
            stamp = struct.unpack_from("<Q", self.buffer, 24)[0] if version == 2 else None
            if stamp == 0:
                raise ValueError("NAVF version 2 capture timestamp is missing")
            pixels = np.frombuffer(bytes(self.buffer[header_size:size]), dtype="<f4" if fmt == 2 else "uint8")
            pixels = pixels.reshape((h, w) if fmt == 2 else (h, w, 4))
            result.append(CameraFrame(cid, frame, stamp, fmt, pixels))
            del self.buffer[:size]
        return result


def depth_points(depth_m, *, hfov_deg, stride=1):
    depth = np.asarray(depth_m, dtype=float)
    if depth.ndim != 2 or not 0 < hfov_deg < 180 or type(stride) is not int or stride < 1:
        raise ValueError("Use a planar depth image, valid horizontal FOV and positive stride")
    h, w = depth.shape
    fx = w / (2 * math.tan(math.radians(hfov_deg) / 2))
    # Pixel centres are u+0.5,v+0.5 in the edge-coordinate image convention.
    rows = np.arange(0, h, stride)[:, None]
    cols = np.arange(0, w, stride)[None, :]
    z = depth[::stride, ::stride]
    points = np.stack(((cols - (w - 1) / 2) * z / fx, (rows - (h - 1) / 2) * z / fx, z), axis=-1).reshape(-1, 3)
    return points[np.isfinite(points).all(axis=1) & (points[:, 2] > 0)]


def transform_matrix(value):
    matrix = np.asarray(value, dtype=float)
    if (
        matrix.shape != (4, 4)
        or not np.isfinite(matrix).all()
        or not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-8, rtol=0)
        or not np.allclose(matrix[:3, :3].T @ matrix[:3, :3], np.eye(3), atol=1e-5, rtol=0)
        or not math.isclose(np.linalg.det(matrix[:3, :3]), 1, abs_tol=1e-5)
    ):
        raise ValueError("Sensor/pose transform must be a finite right-handed rigid 4x4 matrix")
    return matrix.copy()


def transform_points(points, matrix):
    matrix = transform_matrix(matrix)
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("Points must be Nx3")
    return points @ matrix[:3, :3].T + matrix[:3, 3]


@dataclass
class Pose:
    stamp_ns: int
    matrix: np.ndarray

    @property
    def xy_heading(self):
        return float(self.matrix[0, 3]), float(self.matrix[1, 3]), math.atan2(self.matrix[1, 0], self.matrix[0, 0])


def pose_from_telemetry(data):
    stamp = data.get("t_ns")
    if (
        isinstance(stamp, bool)
        or not isinstance(stamp, (str, int))
        or not str(stamp).strip().isdigit()
        or int(stamp) <= 0
    ):
        raise ValueError("Pose requires an exact positive t_ns integer/string capture timestamp")
    values = [data.get(k) for k in ("x", "y", "z", "roll", "pitch", "yaw")]
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError("Pose requires finite Unreal x,y,z,roll,pitch,yaw")
    x, y, z, roll, pitch, yaw = values
    r, p, h = map(math.radians, (roll, pitch, yaw))
    cr, sr, cp, sp, ch, sh = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(h), math.sin(h)
    forward = np.array([-cp * ch, cp * sh, sp])
    up = np.array([cr * sp * ch + sr * sh, ch * sr - cr * sp * sh, cr * cp])
    left = np.cross(up, forward)
    matrix = np.eye(4)
    matrix[:3, :3] = np.column_stack((forward, left, up))
    matrix[:3, 3] = [-x / 100, y / 100, z / 100]
    return Pose(int(stamp), transform_matrix(matrix))


class PoseHistory:
    """Interpolate bracketed capture poses; never silently use arrival/current pose."""

    def __init__(self, *, max_gap_s=0.25):
        self.samples = deque(maxlen=512)
        self.max_gap_ns = max_gap_s * 1e9

    def add(self, pose):
        if self.samples and pose.stamp_ns < self.samples[-1].stamp_ns:
            self.samples.clear()  # new Play/clock; caller also resets the mission
        if self.samples and pose.stamp_ns == self.samples[-1].stamp_ns:
            self.samples[-1] = pose
        else:
            self.samples.append(pose)

    def at(self, stamp_ns):
        for pose in self.samples:
            if abs(pose.stamp_ns - stamp_ns) <= CAPTURE_CLOCK_TOLERANCE_NS:
                return Pose(stamp_ns, pose.matrix.copy())
        for a, b in zip(self.samples, list(self.samples)[1:]):
            if a.stamp_ns < stamp_ns < b.stamp_ns:
                if b.stamp_ns - a.stamp_ns > self.max_gap_ns:
                    break
                alpha = (stamp_ns - a.stamp_ns) / (b.stamp_ns - a.stamp_ns)
                # Orthonormalized interpolation is bounded to small attitude
                # changes; a reset/teleport cannot be smoothed into a fake scan.
                if np.trace(a.matrix[:3, :3].T @ b.matrix[:3, :3]) < 1 + 2 * math.cos(math.pi / 4):
                    raise ValueError("Pose attitude discontinuity during capture")
                matrix = (1 - alpha) * a.matrix + alpha * b.matrix
                u, _, vt = np.linalg.svd(matrix[:3, :3])
                matrix[:3, :3] = u @ vt
                return Pose(stamp_ns, transform_matrix(matrix))
        raise ValueError("No bracketed capture pose; wait for matching telemetry")

    def is_stationary(self, duration_s):
        if not self.samples or self.samples[-1].stamp_ns - self.samples[0].stamp_ns < duration_s * 1e9:
            return False
        end = self.samples[-1]
        values = list(self.samples)
        boundary = end.stamp_ns - duration_s * 1e9
        first = max(i for i, p in enumerate(values) if p.stamp_ns <= boundary)
        relevant = values[first:]
        if any(b.stamp_ns - a.stamp_ns > self.max_gap_ns for a, b in zip(relevant, relevant[1:])):
            return False
        return all(
            np.linalg.norm(p.matrix[:3, 3] - end.matrix[:3, 3]) <= 0.02
            and np.trace(p.matrix[:3, :3].T @ end.matrix[:3, :3]) >= 1 + 2 * math.cos(math.radians(2))
            for p in relevant
        )
