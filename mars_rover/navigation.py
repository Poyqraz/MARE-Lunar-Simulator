"""ROS-free mission core: DEM prior, capture-time sensor geometry and stop/replan.

The optional service lives in nav_service.py. Sensor validity/freshness is a
separate gate from terrain planning. Ground-truth depth is labelled explicitly.
"""

import math
import threading
import time

import numpy as np

from .planning import NoRoute
from .sensors import PoseHistory, depth_points, pose_from_telemetry, transform_matrix, transform_points


class RouteFollower:
    """Low-speed waypoint tracker with rotate-in-place turns, for skid steering."""

    def __init__(self, route, *, speed_m_s=0.15, angular_limit_rad_s=0.6):
        if len(route) < 1 or not 0 < speed_m_s <= 0.5 or not 0 < angular_limit_rad_s <= 2:
            raise ValueError("Invalid route/tracking speed")
        self.route = [tuple(map(float, p)) for p in route]
        if any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in self.route):
            raise ValueError("Invalid route positions")
        self.index = min(1, len(route) - 1)
        self.speed, self.angular_limit = speed_m_s, angular_limit_rad_s
        self.arrived = False

    def command(self, pose):
        x, y, heading = pose
        if not all(math.isfinite(v) for v in pose):
            raise ValueError("Non-finite tracking pose")
        if self.arrived or math.dist((x, y), self.route[-1]) <= 0.25:
            self.arrived = True
            return 0, 0
        while self.index < len(self.route) - 1 and math.dist((x, y), self.route[self.index]) <= 0.15:
            self.index += 1
        tx, ty = self.route[self.index]
        error = (math.atan2(ty - y, tx - x) - heading + math.pi) % (2 * math.pi) - math.pi
        w = max(-self.angular_limit, min(self.angular_limit, 2 * error))
        v = self.speed * max(0, math.cos(error)) if abs(error) < 0.25 else 0
        return v, w


class NavigationSession:
    def __init__(
        self,
        grid,
        config,
        *,
        depth_source="ground_truth",
        min_points=20,
        sensor_timeout_s=0.4,
        speed_m_s=0.15,
        settle_s=2.0,
    ):
        if (
            config.get("schema_version") != 1
            or config.get("manifest_sha256") != grid.manifest_sha256
            or depth_source not in ("ground_truth", "stereo")
            or type(min_points) is not int
            or min_points < 1
            or not 0 < sensor_timeout_s <= 2
            or not 0 < speed_m_s <= 0.5
            or not 0 <= settle_s <= 30
        ):
            raise ValueError("Sensor config must match this terrain; invalid navigation settings")
        try:
            for key, id_key in (("lidar", "sensor_id"), ("depth", "camera_id")):
                settings = config[key]
                transform_matrix(settings["to_body"])
                if type(settings[id_key]) is not int or not 0 <= settings[id_key] <= 255:
                    raise ValueError("Invalid sensor id")
            depth = config["depth"]
            if not 0 < depth["hfov_deg"] < 180:
                raise ValueError("Invalid depth camera FOV")
            if "width" in depth or "height" in depth:
                if any(type(depth[k]) is not int or depth[k] < 1 for k in ("width", "height")):
                    raise ValueError("Invalid depth resolution")
            if depth_source == "stereo":
                rig = config["stereo"]
                transform_matrix(rig["to_body"])
                if (
                    rig["rectified_parallel"] is not True
                    or not 0 < rig["baseline_m"] < 10
                    or not 0 < rig["hfov_deg"] < 180
                    or any(type(rig[k]) is not int or not 0 <= rig[k] <= 255 for k in ("left_id", "right_id"))
                    or len({rig["left_id"], rig["right_id"], depth["camera_id"]}) != 3
                    or any(type(rig[k]) is not int for k in ("width", "height"))
                    or rig["width"] < 96
                    or rig["height"] < 16
                    or rig["width"] * rig["height"] > 1_048_576
                ):
                    raise ValueError("Invalid stereo calibration")
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                f"Invalid {depth_source} sensor configuration (stereo needs a measured rig): {error}"
            ) from error
        self.grid, self.config = grid, config
        self.depth_source, self.min_points, self.timeout, self.speed = (
            depth_source,
            min_points,
            sensor_timeout_s,
            speed_m_s,
        )
        self.settle_s = settle_s
        self.lock = threading.RLock()
        self.history = PoseHistory()
        self.connection_id = None
        self.goal, self.follower = None, None
        self.latest, self.used, self.health = {}, {}, {}
        self.state, self.error = "idle", None
        self.replans, self.plan_revision = 0, -1
        self.pose = None
        self.started_at = None
        self._last_motion = None
        self._motion_xy = None

    def set_goal(self, goal):
        with self.lock:
            goal = tuple(goal)
            row, col = self.grid.cell(goal)
            if self.grid.blocked[row, col]:
                raise NoRoute("Requested goal is blocked; it was not silently moved")
            self.goal, self.follower = tuple(map(float, goal)), None
            self.state, self.error = "waiting_for_sensors", None
            self.started_at, self._last_motion, self._motion_xy = None, None, None

    def stop(self):
        with self.lock:
            self.goal, self.follower = None, None
            self.state = "idle"

    def _reset_link(self):
        self.stop()
        self.history = PoseHistory()
        self.latest.clear()
        self.used.clear()
        self.health.clear()
        self.pose = None
        self.state = "new_session_requires_goal"

    def feed_lidar(self, scan, *, now=None):
        if scan.sensor_id == self.config["lidar"]["sensor_id"]:
            self._feed("lidar", scan, now)

    def feed_camera(self, frame, *, now=None):
        if frame.stamp_ns is None:
            raise ValueError("Unstamped NAVF v1 is playback-only; navigation needs capture time")
        if frame.camera_id == self.config["depth"]["camera_id"] and frame.format == 2:
            settings = self.config["depth"]
            if "width" in settings and frame.pixels.shape[:2] != (settings["height"], settings["width"]):
                raise ValueError("Depth resolution changed since calibration")
            self._feed("ground_truth", frame, now)
        if self.depth_source == "stereo" and frame.format == 1:
            from .stereo import stereo_pair_depth

            pair = self.config["stereo"]
            key = (
                "left"
                if frame.camera_id == pair["left_id"]
                else "right"
                if frame.camera_id == pair["right_id"]
                else None
            )
            if key:
                if frame.pixels.shape[:2] != (pair["height"], pair["width"]):
                    raise ValueError("Stereo resolution changed since calibration")
                self._feed(key, frame, now)
                with self.lock:
                    if "left" in self.latest and "right" in self.latest:
                        left, right = self.latest["left"][0], self.latest["right"][0]
                        if (
                            left.frame_id == right.frame_id
                            and left.stamp_ns == right.stamp_ns
                            and self.used.get("stereo_pair") != (left.frame_id, left.stamp_ns)
                        ):
                            depth = stereo_pair_depth(left, right, pair)
                            self.used["stereo_pair"] = left.frame_id, left.stamp_ns
                            self._feed("stereo", depth, now)

    def _feed(self, key, value, now):
        with self.lock:
            old = self.latest.get(key)
            if old and value.stamp_ns < old[0].stamp_ns:
                return
            self.latest[key] = value, time.monotonic() if now is None else now

    def _consume(self):
        depth_key = self.depth_source
        for key in ("lidar", depth_key):
            if key not in self.latest:
                continue
            frame, received = self.latest[key]
            signature = frame.frame_id, frame.stamp_ns
            if self.used.get(key) == signature:
                continue
            # Wait for a bracketing pose, rather than using the rover's current
            # pose on an asynchronously returned scan/image.
            pose = self.history.at(frame.stamp_ns)
            if self.pose.stamp_ns - frame.stamp_ns > self.timeout * 1e9:
                self.health[key] = {"received_at": received, "valid_inside_points": 0, "capture_stale": True}
                continue
            settings = (
                self.config["lidar"]
                if key == "lidar"
                else self.config["depth"]
                if key == "ground_truth"
                else self.config["stereo"]
            )
            points = frame.points if key == "lidar" else depth_points(frame.depth_m(), hfov_deg=settings["hfov_deg"])
            points = points[np.isfinite(points).all(axis=1) & (np.linalg.norm(points, axis=1) <= 8)]
            matrix = pose.matrix @ transform_matrix(settings["to_body"])
            if key == "stereo" and len(points):
                # A stated one-pixel disparity scenario, not measured error:
                # sigma_Z ~= Z^2/(fx*baseline). Propagate along each viewing
                # ray into map height and refuse an overconfident pit/rock label.
                fx = frame.metres.shape[1] / (2 * math.tan(math.radians(settings["hfov_deg"]) / 2))
                sigma_z = points[:, 2] ** 2 / (fx * settings["baseline_m"])
                height_factor = np.abs((points @ matrix[:3, :3].T)[:, 2] / points[:, 2])
                points = points[3 * sigma_z * height_factor <= self.grid.limits.obstacle_height_m / 2]
            world = transform_points(points, matrix)
            report = self.grid.observe(world)
            self.health[key] = {**report, "received_at": received, "stamp_ns": frame.stamp_ns}
            self.used[key] = signature

    def step(self, bridge_status, *, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            connection = bridge_status.get("connection_id")
            if self.connection_id not in (None, 0) and connection != self.connection_id:
                self._reset_link()
            self.connection_id = connection
            if not bridge_status.get("connected"):
                self.state = "disconnected"
                return 0, 0
            if not self.goal:
                return 0, 0
            if self.state in ("arrived", "blocked", "stalled_or_timed_out"):
                return 0, 0
            age = bridge_status.get("telemetry_age_s")
            if age is None or age > 0.3:
                self.state = "waiting_for_pose"
                return 0, 0
            try:
                pose = pose_from_telemetry(bridge_status.get("telemetry_unreal") or {})
                if self.pose and pose.stamp_ns < self.pose.stamp_ns:
                    self._reset_link()
                    return 0, 0
                self.pose = pose
                self.history.add(pose)
                if (
                    self.follower is None
                    and self.started_at is None
                    and self.settle_s
                    and not self.history.is_stationary(self.settle_s)
                ):
                    self.state = "waiting_for_settle"
                    return 0, 0
                self._consume()
                ready = all(
                    k in self.health
                    and now - self.health[k]["received_at"] <= self.timeout
                    and self.health[k]["valid_inside_points"] >= self.min_points
                    for k in ("lidar", self.depth_source)
                )
                if not ready:
                    self.state = "waiting_for_sensors"
                    return 0, 0
                xyh = self.pose.xy_heading
                if self.follower and self.grid.revision != self.plan_revision:
                    rest = [xyh[:2], *self.follower.route[self.follower.index :]]
                    self.plan_revision = self.grid.revision
                    if not all(self.grid.segment_clear(a, b) for a, b in zip(rest, rest[1:])):
                        self.follower, self.state = None, "replanning"
                        return 0, 0  # send stop BEFORE the next planning cycle
                if self.follower is None:
                    route = self.grid.plan(xyh[:2], self.goal)
                    self.follower = RouteFollower(route, speed_m_s=self.speed)
                    self.plan_revision, self.replans = self.grid.revision, self.replans + 1
                    self.state, self.error = "following", None
                    self.started_at = self.started_at or now
                    self._last_motion, self._motion_xy = now, xyh
                    return 0, 0
                if not self.grid.segment_clear(xyh[:2], self.follower.route[self.follower.index]):
                    self.follower, self.state = None, "replanning"
                    return 0, 0
                command = self.follower.command(xyh)
                if self.follower.arrived:
                    self.state = "arrived"
                    return 0, 0
                if (
                    math.dist(xyh[:2], self._motion_xy[:2]) > 0.02
                    or abs((xyh[2] - self._motion_xy[2] + math.pi) % (2 * math.pi) - math.pi) > 0.02
                ):
                    self._last_motion, self._motion_xy = now, xyh
                if now - self._last_motion > 15 or now - self.started_at > 1800:
                    self.state = "stalled_or_timed_out"
                    return 0, 0
                self.state = "following"
                # Check the commanded short arc against the inflated map too;
                # a curved tracker must not cut outside the straight grid route.
                x, y, yaw = xyh
                for _ in range(10):
                    previous = x, y
                    x += command[0] * math.cos(yaw) * 0.1
                    y += command[0] * math.sin(yaw) * 0.1
                    yaw += command[1] * 0.1
                    if not self.grid.segment_clear(previous, (x, y)):
                        return 0, command[1]
                return command
            except (ValueError, KeyError, TypeError) as error:
                self.error = str(error)
                self.state = "blocked" if isinstance(error, NoRoute) else "waiting_for_sensors"
                return 0, 0

    def status(self):
        with self.lock:
            return {
                "state": self.state,
                "goal": self.goal,
                "error": self.error,
                "replans": self.replans,
                "map_revision": self.grid.revision,
                "depth_source": self.depth_source,
                "sensor_health": self.health.copy(),
                "calibration_source": self.config.get("source"),
                "pose_local_m": self.pose.xy_heading if self.pose else None,
                "route": self.follower.route if self.follower else [],
                "goal_tolerance_m": 0.25,
                "global_map_source": "measured DEM prior",
                "micro_geometry_complete": False,
                "native_rover_verified": False,
                "terrain_manifest_sha256": self.grid.manifest_sha256,
            }
