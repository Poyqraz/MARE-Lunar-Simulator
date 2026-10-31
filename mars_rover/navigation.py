"""ROS-free mission core: DEM prior, capture-time sensor geometry and stop/replan.

The optional service lives in nav_service.py. Sensor validity/freshness is a
separate gate from terrain planning. Ground-truth depth is labelled explicitly.
"""

import copy
from collections import deque
from dataclasses import dataclass
import math
import threading
import time

import numpy as np

from .planning import NoRoute
from .mission import MissionHistory
from .sensors import (
    CAPTURE_CLOCK_TOLERANCE_NS,
    PoseHistory,
    depth_points,
    pose_from_telemetry,
    transform_matrix,
    transform_points,
)

LATE_DATA_ERROR = "Pose or sensor data expired during control processing"


@dataclass(frozen=True)
class PreparedGroundTruthFrame:
    """Depth points in the camera frame; capture pose is applied later."""

    frame_id: int
    stamp_ns: int
    points: np.ndarray
    preparation_s: float


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
        obstacle_diagnostics=False,
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
            or type(obstacle_diagnostics) is not bool
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
        self.mission = MissionHistory(grid.manifest_sha256)
        self.connected = False
        self.observer_error = None
        self.sensor_observation_error = None
        self.sensor_wait_details = {}
        self._pose_received_at = self._unique_pose_at = None
        self._late_decision = False
        self.obstacle_diagnostics = obstacle_diagnostics
        self._obstacle_frames = deque(maxlen=128)
        self._obstacle_frames_evicted = 0
        self._last_planning_failure = None

    def set_goal(self, goal):
        with self.lock:
            goal = tuple(goal)
            row, col = self.grid.cell(goal)
            if self.grid.blocked[row, col]:
                raise NoRoute("Requested goal is blocked; it was not silently moved")
            self.mission.begin(goal)
            self.goal, self.follower = tuple(map(float, goal)), None
            self.state, self.error = "waiting_for_sensors", None
            self.sensor_wait_details = {}
            self.started_at, self._last_motion, self._motion_xy = None, None, None
            self.replans, self.plan_revision = 0, -1

    def stop(self):
        with self.lock:
            self.mission.finish("stopped")
            self.goal, self.follower = None, None
            self.state = "idle"
            self.sensor_wait_details = {}

    def _reset_link(self, reason="new_connection"):
        self.mission.new_session(reason)
        self.stop()
        self.history = PoseHistory()
        self.latest.clear()
        self.used.clear()
        self.health.clear()
        self.pose = None
        self._pose_received_at = self._unique_pose_at = None
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
            received = time.monotonic() if now is None else now
            if self.depth_source == "ground_truth":
                # This camera-only projection needs neither the session lock
                # nor the capture pose. Keep the original arrival time so the
                # time spent here still counts against freshness.
                started = time.monotonic()
                points = depth_points(frame.depth_m(), hfov_deg=settings["hfov_deg"])
                points = points[np.isfinite(points).all(axis=1) & (np.linalg.norm(points, axis=1) <= 8)]
                frame = PreparedGroundTruthFrame(frame.frame_id, frame.stamp_ns, points,
                                                 max(0.0, time.monotonic() - started))
            self._feed("ground_truth", frame, received)
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
                        left, left_received = self.latest["left"]
                        right, right_received = self.latest["right"]
                        if (
                            left.frame_id == right.frame_id
                            and left.stamp_ns == right.stamp_ns
                            and self.used.get("stereo_pair") != (left.frame_id, left.stamp_ns)
                        ):
                            depth = stereo_pair_depth(left, right, pair)
                            self.used["stereo_pair"] = left.frame_id, left.stamp_ns
                            # A stereo result cannot be fresher than its older
                            # input, including time spent computing disparity.
                            self._feed("stereo", depth, min(left_received, right_received))

    def _feed(self, key, value, now):
        received = time.monotonic() if now is None else now
        with self.lock:
            old = self.latest.get(key)
            if old and value.stamp_ns < old[0].stamp_ns:
                return
            self.latest[key] = value, received

    def _capture_too_old(self, stamp_ns):
        # Sensor and pose clocks are represented at different precisions. This
        # allowance is at most 1.024 microseconds, not a new latency budget;
        # independently require fresh arrival and pose times as before.
        return self.pose.stamp_ns - stamp_ns > self.timeout * 1e9 + CAPTURE_CLOCK_TOLERANCE_NS

    def _consume(self):
        depth_key = self.depth_source
        for key in ("lidar", depth_key):
            if key not in self.latest:
                continue
            frame, received = self.latest[key]
            signature = frame.frame_id, frame.stamp_ns
            if self.used.get(key) == signature:
                continue
            processing_started = time.monotonic()
            # Wait for a bracketing pose, rather than using the rover's current
            # pose on an asynchronously returned scan/image.
            pose = self.history.at(frame.stamp_ns)
            if self._capture_too_old(frame.stamp_ns):
                self.health[key] = {"received_at": received, "valid_inside_points": 0,
                                    "capture_stale": True, "stamp_ns": frame.stamp_ns}
                continue
            settings = (
                self.config["lidar"]
                if key == "lidar"
                else self.config["depth"]
                if key == "ground_truth"
                else self.config["stereo"]
            )
            prepared = key == "ground_truth" and isinstance(frame, PreparedGroundTruthFrame)
            if prepared:
                points = frame.points
            else:
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
            if self.obstacle_diagnostics:
                focus = (pose.xy_heading[:2], self.goal) if self.goal else (pose.xy_heading[:2],)
                report = self.grid.observe(world, diagnostics=True, diagnostic_focus=focus)
                diagnostic = report.pop("diagnostics")
                if report["map_changed"] or "collection_error" in diagnostic:
                    self._obstacle_frames_evicted += int(len(self._obstacle_frames) == self._obstacle_frames.maxlen)
                    self._obstacle_frames.append({
                        "source": key, "frame_id": int(frame.frame_id), "stamp_ns": str(frame.stamp_ns),
                        "session_id": self.mission.session_id,
                        "mission_id": self.mission.current["mission_id"] if self.mission.active else None,
                        "map_revision": self.grid.revision, "world_from_body": pose.matrix.tolist(),
                        "sensor_to_body": transform_matrix(settings["to_body"]).tolist(),
                        "positive_obstacles": report["positive_obstacles"],
                        "negative_obstacles": report["negative_obstacles"],
                        "valid_inside_points": report["valid_inside_points"], **diagnostic,
                    })
            else:
                report = self.grid.observe(world)
            locked_processing = max(0.0, time.monotonic() - processing_started)
            preparation = frame.preparation_s if prepared else 0.0
            self.health[key] = {**report, "received_at": received, "stamp_ns": frame.stamp_ns,
                                "processing_s": preparation + locked_processing}
            if prepared:
                self.health[key].update(preparation_s=preparation, locked_processing_s=locked_processing)
            self.used[key] = signature

    def _observe_bridge(self, bridge_status, now):
        connection = bridge_status.get("connection_id")
        if self.connection_id not in (None, 0) and connection != self.connection_id:
            self._reset_link()
        self.connection_id = connection
        self.connected = bool(bridge_status.get("connected"))
        if not self.connected:
            if connection not in (None, 0):
                self.mission.finish("disconnected")
                self.goal, self.follower = None, None
            self.state = "disconnected"
            return False
        age = bridge_status.get("telemetry_age_s")
        if type(age) not in (float, int) or not math.isfinite(age) or not 0 <= age <= 0.3:
            self.observer_error = "No fresh pose telemetry"
            if self.goal:
                self.state = "waiting_for_pose"
            return False
        try:
            pose = pose_from_telemetry(bridge_status.get("telemetry_unreal") or {})
            previous = self.pose
            if previous:
                dt = (pose.stamp_ns - previous.stamp_ns) / 1e9
                moved = math.dist(pose.xy_heading[:2], previous.xy_heading[:2])
                if dt < 0:
                    self._reset_link("clock_reset")
                elif (dt == 0 and not np.allclose(pose.matrix, previous.matrix, atol=1e-6, rtol=0)) or (
                    0 < dt <= 0.25 and moved > 0.25 + 2 * dt
                ):
                    self._reset_link("teleport")
                elif dt > 0.25:
                    # A missing interval is not a bracketing pose or a clear
                    # corridor. Fresh sensor captures must re-establish health.
                    self.history = PoseHistory()
                    self.latest.clear()
                    self.used.clear()
                    self.health.clear()
                    self.follower = None
            if self.pose is None or pose.stamp_ns != self.pose.stamp_ns:
                self._unique_pose_at = now
            self.pose = pose
            self.history.add(pose)
            self.mission.observe(pose)
            self._pose_received_at = now - age
            self.observer_error = None
            if self.state == "disconnected" and not self.goal:
                self.state = "idle"
            try:
                self._consume()
                self.sensor_observation_error = None
            except (ValueError, KeyError, TypeError) as error:
                self.sensor_observation_error = str(error)
            return True
        except (ValueError, KeyError, TypeError) as error:
            self.observer_error = str(error)
            if self.goal:
                self.state = "waiting_for_pose"
            return False

    def step(self, bridge_status, *, now=None, wall_clock=None):
        if now is None:
            now = time.monotonic()
            wall_clock = time.monotonic if wall_clock is None else wall_clock
        with self.lock:
            self._late_decision = False
            self.sensor_wait_details = {}
            previous_state = self.state
            ready = self._observe_bridge(bridge_status, now)
            command = self._drive(now) if ready else (0, 0)
            if self.follower and self.pose:
                self.mission.progress(self.follower.index, self.pose.xy_heading[:2])
            terminal = self.state in ("arrived", "blocked", "stalled_or_timed_out")
            if ready and self.goal and (command != (0, 0) or (terminal and self.state != previous_state)):
                deadline = self.motion_deadline()
                finished_at = wall_clock() if wall_clock is not None else now
                if (type(finished_at) not in (float, int) or not math.isfinite(finished_at)
                        or finished_at < now or deadline is None or deadline <= finished_at):
                    if self.state == "arrived" and self.follower:
                        self.follower.arrived = False
                    self.state, self.error = "waiting_for_fresh_data", LATE_DATA_ERROR
                    self._late_decision = True
                    command = (0, 0)
                elif self.error == LATE_DATA_ERROR:
                    self.error = None
            details = (
                {"sensors": self.sensor_wait_details}
                if self.state == "waiting_for_sensors" and self.sensor_wait_details
                else None
            )
            self.mission.state(self.state, self.error, details=details)
            return command

    def motion_deadline(self):
        """Latest monotonic time a command based on the current observations may be sent."""
        with self.lock:
            if not self.connected or self.pose is None:
                return None
            times = (self._pose_received_at, self._unique_pose_at)
            if any(type(t) not in (int, float) or not math.isfinite(t) for t in times):
                return None
            deadlines = [t + 0.3 for t in times]
            for key in ("lidar", self.depth_source):
                report = self.health.get(key)
                if not report or report.get("valid_inside_points", 0) < self.min_points:
                    return None
                received, stamp = report.get("received_at"), report.get("stamp_ns")
                if (type(received) not in (int, float) or not math.isfinite(received)
                        or type(stamp) is not int
                        or self._capture_too_old(stamp)
                        or stamp - self.pose.stamp_ns > CAPTURE_CLOCK_TOLERANCE_NS):
                    return None
                deadlines.append(received + self.timeout)
            return min(deadlines)

    def _drive(self, now):
        with self.lock:
            self.sensor_wait_details = {}
            if not self.goal:
                return 0, 0
            if self.state in ("arrived", "blocked", "stalled_or_timed_out"):
                return 0, 0
            try:
                if (
                    self.follower is None
                    and self.started_at is None
                    and self.settle_s
                    and not self.history.is_stationary(self.settle_s)
                ):
                    self.state = "waiting_for_settle"
                    return 0, 0
                self._consume()
                self.sensor_wait_details = self._sensor_wait_reasons(now)
                if self.sensor_wait_details:
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
                    self.mission.plan(route, self.grid.revision)
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
                if isinstance(error, NoRoute) and self.obstacle_diagnostics:
                    try:
                        self._last_planning_failure = {
                            "mission_id": self.mission.current["mission_id"] if self.mission.current else None,
                            "stamp_ns": str(self.pose.stamp_ns), "map_revision": self.grid.revision,
                            "error": str(error), "start": self.grid.blockage_details(self.pose.xy_heading[:2]),
                            "goal": self.grid.blockage_details(self.goal),
                        }
                    except Exception as diagnostic_error:  # Do not alter the stop on NoRoute.
                        self._last_planning_failure = {"collection_error": str(diagnostic_error)[:256]}
                return 0, 0

    def _sensor_wait_reasons(self, now):
        """Record why a decision stopped; do not infer it later from a snapshot."""
        details = {}
        for key in ("lidar", self.depth_source):
            report = self.health.get(key)
            if report is None:
                details[key] = {"reasons": ["missing"]}
                continue
            reasons = []
            age = now - report["received_at"]
            stamp = report.get("stamp_ns")
            capture_age_ns = self.pose.stamp_ns - stamp if type(stamp) is int else None
            if age > self.timeout:
                reasons.append("arrival_stale")
            if report.get("capture_stale") or (stamp is not None and self._capture_too_old(int(stamp))):
                reasons.append("capture_stale")
            elif report["valid_inside_points"] < self.min_points:
                reasons.append("insufficient_points")
            if stamp is None:
                reasons.append("capture_time_missing")
            if reasons:
                details[key] = {
                    "reasons": reasons,
                    "arrival_age_s": max(0.0, age),
                    "capture_age_s": capture_age_ns / 1e9 if capture_age_ns is not None else None,
                    "valid_inside_points": report["valid_inside_points"],
                }
        return details

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

    def mission_snapshot(self, bridge_status=None, *, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            age = max(0.0, now - self._pose_received_at) if self._pose_received_at is not None else None
            fresh = self.connected and age is not None and age <= 0.3 and self.observer_error is None
            advancing = self._unique_pose_at is not None and now - self._unique_pose_at <= 0.3
            health = {}
            for key, report in self.health.items():
                health[key] = {k: v for k, v in report.items() if k != "received_at"}
                if "stamp_ns" in health[key]:
                    health[key]["stamp_ns"] = str(health[key]["stamp_ns"])
                health[key]["received_age_s"] = max(0.0, now - report["received_at"])
            return copy.deepcopy(
                {
                    "schema_version": 1,
                    "session_id": self.mission.session_id,
                    "snapshot_seq": self.mission.revision,
                    "coordinate_frame_id": "mars_local_east_north_up_metres",
                    "terrain_manifest_sha256": self.grid.manifest_sha256,
                    "live_pose": self.mission.latest,
                    "pose_fresh": fresh,
                    "pose_age_s": age,
                    "capture_clock_advancing": advancing,
                    "speed_estimate_m_s": self.mission.speed_estimate if fresh and advancing else None,
                    "position_source": "simulation telemetry",
                    "telemetry_format": (bridge_status or {}).get("telemetry_format"),
                    "telemetry_timing": (bridge_status or {}).get("telemetry_timing"),
                    "mission": self.mission.summary(),
                    "state": self.state,
                    "observer_error": self.observer_error,
                    "sensor_observation_error": self.sensor_observation_error,
                    "sensor_health": health,
                    "sensor_wait_details": self.sensor_wait_details,
                    "depth_source": self.depth_source,
                    "map_revision": self.grid.revision,
                    "wheel_command_m_s": (bridge_status or {}).get("wheel_command_m_s"),
                    "wire_command": (bridge_status or {}).get("wire_command"),
                    "unavailable": {
                        "battery_percent": None,
                        "motor_rpm": None,
                        "motor_current_a": None,
                        "motor_temperature_c": None,
                    },
                    "history_storage": "bounded memory; explicit export",
                    "native_rover_verified": False,
                    "micro_geometry_complete": False,
                }
            )

    def mission_export(self):
        with self.lock:
            captured = self.mission.capture_export()
            if self.obstacle_diagnostics:
                captured["obstacle_diagnostics"] = {
                    "enabled": True, "max_frames": self._obstacle_frames.maxlen,
                    "frames_evicted": self._obstacle_frames_evicted,
                    "frames": list(self._obstacle_frames), "last_planning_failure": self._last_planning_failure,
                }
        return copy.deepcopy(captured)
