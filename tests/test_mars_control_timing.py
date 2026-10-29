"""Late control decisions must not extend the lifetime of stale sensor data."""

from types import SimpleNamespace

import numpy as np
import pytest

from mars_rover.drive import Calibration, CommandState
from mars_rover.nav_service import NavigationService
from mars_rover.planning import PlanningLimits, TerrainMap
from mars_rover.navigation import NavigationSession, RouteFollower
from mars_rover.sensors import CameraFrame, LidarScan, pose_from_telemetry


class SingleControlTick:
    def __init__(self):
        self.done = False
        self.wait_s = None

    def is_set(self):
        return self.done

    def wait(self, timeout):
        self.wait_s = timeout
        self.done = True

    def set(self):
        self.done = True


@pytest.mark.parametrize("processing_s,expected_wait_s", [(0.01, 0.04), (0.07, 0.001), (0.3, 0.001)])
def test_control_scheduler_includes_processing_time_in_its_period(monkeypatch, processing_s, expected_wait_s):
    import mars_rover.nav_service as module

    grid = TerrainMap(np.zeros((10, 10)), 1, PlanningLimits(robot_radius_m=0))
    config = {
        "schema_version": 1,
        "manifest_sha256": None,
        "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
        "depth": {"camera_id": 4, "to_body": np.eye(4).tolist(), "hfov_deg": 90},
    }
    service = NavigationService(grid, config, tcp_port=0, bridge_http_port=0, http_port=0,
                                lidar_port=0, camera_port=0)
    clock = SimpleNamespace(value=100.0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.value))
    monkeypatch.setattr(service.bridge, "status", lambda: {"connected": False})

    def work(*_args, **_kwargs):
        clock.value += processing_s
        return 0, 0

    monkeypatch.setattr(service.session, "step", work)
    ending = SingleControlTick()
    service.ending = ending
    try:
        service._control()
        assert ending.wait_s == pytest.approx(expected_wait_s)
        assert service.session.goal is None
        assert all(v == 0 for v in service.bridge.state.speeds.values())
    finally:
        service.close()


@pytest.mark.parametrize("earliest,processing_delay", [("pose", 0.31), ("lidar", 0.21), ("depth", 0.21)])
def test_slow_control_tick_does_not_dispatch_a_late_motion_command(monkeypatch, earliest, processing_delay):
    import mars_rover.nav_service as module

    grid = TerrainMap(np.zeros((10, 10)), 1, PlanningLimits(robot_radius_m=0))
    config = {
        "schema_version": 1,
        "manifest_sha256": None,
        "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
        "depth": {"camera_id": 4, "to_body": np.eye(4).tolist(), "hfov_deg": 90},
    }
    service = NavigationService(grid, config, tcp_port=0, bridge_http_port=0, http_port=0,
                                lidar_port=0, camera_port=0, min_points=1)
    clock = SimpleNamespace(value=100.0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.value), raising=False)
    session = service.session
    stamp = 1700000000000000000
    session.pose = pose_from_telemetry(dict(x=-500, y=500, z=0, roll=0, pitch=0, yaw=180, t_ns=str(stamp)))
    session.goal = (8, 5)
    session.connected, session.connection_id = True, 1
    session._pose_received_at = session._unique_pose_at = 100.0
    session.health = {
        "lidar": {"received_at": 99.8 if earliest == "lidar" else 100.0,
                  "valid_inside_points": 1, "stamp_ns": stamp},
        "ground_truth": {"received_at": 99.8 if earliest == "depth" else 100.0,
                         "valid_inside_points": 1, "stamp_ns": stamp},
    }
    service.bridge.state.connect()
    service.bridge.connection_id = 1
    monkeypatch.setattr(service.bridge, "status", lambda: {"connected": True, "connection_id": 1})

    def slow_step(*_args, **_kwargs):
        clock.value += processing_delay
        return 0.15, 0

    monkeypatch.setattr(session, "step", slow_step)
    submitted = []
    monkeypatch.setattr(service.bridge.state, "submit_twist", lambda *args, **kwargs: submitted.append(args))
    service.ending = SingleControlTick()
    try:
        service._control()
        assert submitted == []
        assert all(v == 0 for v in service.bridge.state.speeds.values())
    finally:
        service.close()


@pytest.mark.parametrize("connection_changed", [False, True])
def test_control_dispatch_checks_connection_and_preserves_the_observation_deadline(monkeypatch, connection_changed):
    import mars_rover.nav_service as module

    grid = TerrainMap(np.zeros((10, 10)), 1, PlanningLimits(robot_radius_m=0))
    config = {
        "schema_version": 1,
        "manifest_sha256": None,
        "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
        "depth": {"camera_id": 4, "to_body": np.eye(4).tolist(), "hfov_deg": 90},
    }
    service = NavigationService(grid, config, tcp_port=0, bridge_http_port=0, http_port=0,
                                lidar_port=0, camera_port=0, min_points=1)
    clock = SimpleNamespace(value=100.0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.value))
    session = service.session
    stamp = 1700000000000000000
    session.pose = pose_from_telemetry(dict(x=-500, y=500, z=0, roll=0, pitch=0, yaw=180, t_ns=str(stamp)))
    session.goal = (8, 5)
    session.connected, session.connection_id = True, 1
    session._pose_received_at = session._unique_pose_at = 100.0
    session.health = {
        key: {"received_at": 100.0, "valid_inside_points": 1, "stamp_ns": stamp}
        for key in ("lidar", "ground_truth")
    }
    service.bridge.state.connect()
    service.bridge.connection_id = 1
    monkeypatch.setattr(service.bridge, "status", lambda: {"connected": True, "connection_id": 1})

    def step(*_args, **_kwargs):
        clock.value = 100.05
        if connection_changed:
            service.bridge.connection_id = 2
        return 0.15, 0

    monkeypatch.setattr(session, "step", step)
    submitted = []
    monkeypatch.setattr(service.bridge.state, "submit_twist", lambda *args, **kwargs: submitted.append((args, kwargs)))
    service.ending = SingleControlTick()
    try:
        service._control()
        if connection_changed:
            assert submitted == []
        else:
            assert submitted[0][0] == (0.15, 0)
            assert submitted[0][1]["valid_until"] == pytest.approx(100.3)
    finally:
        service.close()


def test_wheel_command_expires_at_sensor_deadline_even_if_watchdog_is_not_yet_due():
    state = CommandState(Calibration(), timeout_s=0.3)
    state.connect()
    state.submit_wheels(dict.fromkeys(("FL", "FR", "BL", "BR"), 0.1), now=10, valid_until=10.1)
    assert state.sample(now=10.09)["FL"] != 0
    assert state.sample(now=10.1)["FL"] == 0


@pytest.mark.parametrize("deadline", [10.0, 9.9, float("nan"), float("inf"), True])
def test_invalid_or_already_expired_deadline_clears_an_existing_command(deadline):
    state = CommandState(Calibration())
    state.connect()
    wheels = dict.fromkeys(("FL", "FR", "BL", "BR"), 0.1)
    state.submit_wheels(wheels, now=10.0)
    with pytest.raises(ValueError):
        state.submit_wheels(wheels, now=10.0, valid_until=deadline)
    assert all(v == 0 for v in state.speeds.values())


def test_slow_real_sensor_observation_cannot_submit_stale_motion(monkeypatch):
    import mars_rover.nav_service as module

    grid = TerrainMap(np.zeros((20, 20)), 1, PlanningLimits(robot_radius_m=0))
    config = {
        "schema_version": 1,
        "manifest_sha256": None,
        "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
        "depth": {"camera_id": 4, "hfov_deg": 90,
                  "to_body": [[0, 0, 1, 0], [-1, 0, 0, 0], [0, -1, 0, 1], [0, 0, 0, 1]]},
    }
    service = NavigationService(grid, config, tcp_port=0, bridge_http_port=0, http_port=0,
                                lidar_port=0, camera_port=0, min_points=1, settle_s=0)
    clock = SimpleNamespace(value=100.0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.value))
    service.bridge.state.connect()
    service.bridge.connection_id = 1
    session = service.session
    session.set_goal((10, 5))
    stamp = 1700000000000000000
    telemetry = dict(x=-500, y=500, z=0, roll=0, pitch=0, yaw=180, t_ns=str(stamp))
    status = {"connected": True, "connection_id": 1, "telemetry_age_s": 0, "telemetry_unreal": telemetry}
    monkeypatch.setattr(service.bridge, "status", lambda: status)
    depth = np.full((3, 3), np.nan, dtype="float32")
    depth[2, 1] = 150

    def feed(frame_id):
        current = int(telemetry["t_ns"])
        session.feed_lidar(LidarScan(0, frame_id, current, np.array([[2.0, 0, 0]]), 1, 1), now=clock.value)
        session.feed_camera(CameraFrame(4, frame_id, current, 2, depth), now=clock.value)

    try:
        feed(1)
        service.ending = SingleControlTick()
        service._control()  # Plan with fresh input; the first cycle remains stopped.
        assert session.follower is not None
        clock.value = 100.1
        telemetry["t_ns"] = str(stamp + 100_000_000)
        feed(2)
        original_observe = grid.observe

        def delayed_observe(points):
            clock.value += 0.2
            return original_observe(points)

        monkeypatch.setattr(grid, "observe", delayed_observe)
        submitted = []
        monkeypatch.setattr(service.bridge.state, "submit_twist", lambda *args, **kwargs: submitted.append(args))
        service.ending = SingleControlTick()
        service._control()
        assert submitted == []
        assert session.state == "waiting_for_fresh_data"
        assert service.control_timing()["expired_decisions"] == 1
        assert all(v == 0 for v in service.bridge.state.speeds.values())
    finally:
        service.close()


def test_control_timing_observes_slow_cycles_without_creating_a_goal(monkeypatch):
    import mars_rover.nav_service as module

    grid = TerrainMap(np.zeros((10, 10)), 1, PlanningLimits(robot_radius_m=0))
    config = {
        "schema_version": 1,
        "manifest_sha256": None,
        "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
        "depth": {"camera_id": 4, "to_body": np.eye(4).tolist(), "hfov_deg": 90},
    }
    service = NavigationService(grid, config, tcp_port=0, bridge_http_port=0, http_port=0,
                                lidar_port=0, camera_port=0)
    clock = SimpleNamespace(value=100.0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.value))
    monkeypatch.setattr(service.bridge, "status", lambda: {"connected": False})

    def slow_step(*_args, **_kwargs):
        clock.value += 0.26
        return 0, 0

    monkeypatch.setattr(service.session, "step", slow_step)
    service.ending = SingleControlTick()
    try:
        service._control()
        report = service.control_timing()
        assert report["cycles"] == 1
        assert report["cycles_over_50ms"] == 1
        assert report["cycles_over_250ms"] == 1
        assert report["max_cycle_s"] == pytest.approx(0.26)
        assert report["expired_decisions"] == 0
        assert service.session.goal is None
        assert all(v == 0 for v in service.bridge.state.speeds.values())
    finally:
        service.close()


@pytest.mark.parametrize("delay,arrives", [(0.31, False), (0.05, True)])
def test_arrival_requires_fresh_pose_after_observation(monkeypatch, delay, arrives):
    grid = TerrainMap(np.zeros((10, 10)), 1, PlanningLimits(robot_radius_m=0))
    config = {
        "schema_version": 1,
        "manifest_sha256": None,
        "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
        "depth": {"camera_id": 4, "to_body": np.eye(4).tolist(), "hfov_deg": 90},
    }
    session = NavigationSession(grid, config, min_points=1, settle_s=0)
    stamp = 1700000000000000000
    session.pose = pose_from_telemetry(dict(x=-500, y=500, z=0, roll=0, pitch=0, yaw=180, t_ns=str(stamp)))
    session.set_goal((5.1, 5))
    session.follower = RouteFollower([(5, 5), (5.1, 5)])
    session.started_at = 100.0
    session.connected, session.connection_id = True, 1
    session._pose_received_at = session._unique_pose_at = 100.0
    session.health = {
        key: {"received_at": 100.0, "valid_inside_points": 1, "stamp_ns": stamp}
        for key in ("lidar", "ground_truth")
    }
    clock = SimpleNamespace(value=100.0)

    def slow_observation(*_args):
        clock.value += delay
        return True

    monkeypatch.setattr(session, "_observe_bridge", slow_observation)
    monkeypatch.setattr(session, "_consume", lambda: None)
    assert session.step({}, now=100.0, wall_clock=lambda: clock.value) == (0, 0)
    assert session.state == ("arrived" if arrives else "waiting_for_fresh_data")
    assert session.mission.active is (not arrives)
    assert session.follower.arrived is arrives


def test_sensor_arrival_time_does_not_move_forward_while_waiting_for_session_lock(monkeypatch):
    import mars_rover.navigation as module

    grid = TerrainMap(np.zeros((10, 10)), 1, PlanningLimits(robot_radius_m=0))
    config = {
        "schema_version": 1,
        "manifest_sha256": None,
        "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
        "depth": {"camera_id": 4, "to_body": np.eye(4).tolist(), "hfov_deg": 90},
    }
    session = NavigationSession(grid, config)
    clock = SimpleNamespace(value=100.0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.value))

    class DelayedLock:
        def __enter__(self):
            clock.value += 0.5

        def __exit__(self, *_args):
            pass

    session.lock = DelayedLock()
    session.feed_lidar(LidarScan(0, 1, 1700000000000000000, np.zeros((1, 3)), 1, 1))
    assert session.latest["lidar"][1] == 100.0


def test_stereo_result_keeps_the_older_input_arrival_time(monkeypatch):
    import mars_rover.stereo as stereo_module

    grid = TerrainMap(np.zeros((10, 10)), 1, PlanningLimits(robot_radius_m=0))
    config = {
        "schema_version": 1,
        "manifest_sha256": None,
        "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
        "depth": {"camera_id": 4, "to_body": np.eye(4).tolist(), "hfov_deg": 90},
        "stereo": {"left_id": 1, "right_id": 2, "to_body": np.eye(4).tolist(), "hfov_deg": 90,
                   "width": 96, "height": 16, "baseline_m": 0.2, "rectified_parallel": True},
    }
    session = NavigationSession(grid, config, depth_source="stereo")
    stamp = 1700000000000000000
    monkeypatch.setattr(stereo_module, "stereo_pair_depth", lambda *_args: SimpleNamespace(frame_id=1, stamp_ns=stamp))
    pixels = np.zeros((16, 96, 4), dtype=np.uint8)
    session.feed_camera(CameraFrame(1, 1, stamp, 1, pixels), now=100.0)
    session.feed_camera(CameraFrame(2, 1, stamp, 1, pixels), now=100.2)
    assert session.latest["stereo"][1] == 100.0
