import importlib
import math

import numpy as np
import pytest


def nav():
    return importlib.import_module("mars_rover.navigation")


def test_sensor_calibration_rejects_changed_resolution_and_invalid_stereo_before_motion():
    from mars_rover.planning import PlanningLimits, TerrainMap
    from mars_rover.sensors import CameraFrame

    grid = TerrainMap(np.zeros((20, 20)), 1, PlanningLimits(robot_radius_m=0))
    config = {
        "schema_version": 1,
        "manifest_sha256": None,
        "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
        "depth": {"camera_id": 4, "hfov_deg": 90, "to_body": np.eye(4).tolist(), "width": 3, "height": 3},
    }
    session = nav().NavigationSession(grid, config)
    with pytest.raises(ValueError, match="resolution"):
        session.feed_camera(CameraFrame(4, 1, 1700000000000000000, 2, np.zeros((4, 3))))
    with pytest.raises(ValueError, match="Stereo|stereo"):
        nav().NavigationSession(grid, config, depth_source="stereo")
    config["stereo"] = {
        "left_id": 1,
        "right_id": 2,
        "to_body": np.eye(4).tolist(),
        "hfov_deg": 90,
        "width": 192,
        "height": 64,
        "baseline_m": -0.2,
        "rectified_parallel": True,
    }
    with pytest.raises(ValueError, match="Stereo|stereo"):
        nav().NavigationSession(grid, config, depth_source="stereo")
    config["stereo"]["baseline_m"] = 0.2
    session = nav().NavigationSession(grid, config, depth_source="stereo")
    with pytest.raises(ValueError, match="resolution"):
        session.feed_camera(CameraFrame(1, 1, 1700000000000000000, 1, np.zeros((64, 96, 4), dtype=np.uint8)))


def test_closed_loop_waypoints_reach_goal_and_stop():
    follower = nav().RouteFollower([(2, 2), (5, 2), (5, 5)])
    x, y, yaw = 2.0, 2.0, 0.0
    for _ in range(4000):
        v, w = follower.command((x, y, yaw))
        x += v * math.cos(yaw) * 0.05
        y += v * math.sin(yaw) * 0.05
        yaw += w * 0.05
        if follower.arrived:
            break
    assert math.hypot(x - 5, y - 5) <= 0.25
    assert follower.command((x, y, yaw)) == (0, 0)


def test_session_waits_for_both_sensors_and_stops_on_stale_data():
    p = importlib.import_module("mars_rover.planning")
    s = importlib.import_module("mars_rover.sensors")
    grid = p.TerrainMap(np.zeros((20, 20)), 1, p.PlanningLimits(robot_radius_m=0))
    # Test extrinsic: optical z forward -> local/body x forward; optical y down.
    optical = [[0, 0, 1, 0], [-1, 0, 0, 0], [0, -1, 0, 1], [0, 0, 0, 1]]
    config = {
        "schema_version": 1,
        "source": "test fixture",
        "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
        "depth": {"camera_id": 4, "hfov_deg": 90, "to_body": optical},
        "manifest_sha256": None,
    }
    session = nav().NavigationSession(grid, config, min_points=1, settle_s=0)
    session.set_goal((10, 5))
    telemetry = dict(x=-500, y=500, z=0, roll=0, pitch=0, yaw=180, t_ns="1700000000000000000")
    status = {"connected": True, "connection_id": 1, "telemetry_age_s": 0, "telemetry_unreal": telemetry}
    assert session.step(status, now=1) == (0, 0)
    # A downward point at local (7,5,0); both sensors see the actual ground.
    session.feed_lidar(s.LidarScan(0, 1, int(telemetry["t_ns"]), np.array([[2.0, 0, 0]]), 1, 1), now=1)
    assert session.step(status, now=1.01) == (0, 0)
    depth = np.array([[np.nan, np.nan, np.nan], [np.nan, np.nan, np.nan], [np.nan, 150, np.nan]], dtype="float32")
    session.feed_camera(s.CameraFrame(4, 1, int(telemetry["t_ns"]), 2, depth), now=1)
    session.step(status, now=1.02)  # plan while stopped
    assert session.step(status, now=1.03)[0] > 0
    assert session.step(status, now=2) == (0, 0)
    assert session.status()["state"] == "waiting_for_sensors"


def test_new_play_connection_cancels_the_old_goal():
    p = importlib.import_module("mars_rover.planning")
    grid = p.TerrainMap(np.zeros((10, 10)), 1, p.PlanningLimits(robot_radius_m=0))
    config = {
        "schema_version": 1,
        "source": "test",
        "manifest_sha256": None,
        "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
        "depth": {"camera_id": 4, "to_body": np.eye(4).tolist(), "hfov_deg": 90},
    }
    session = nav().NavigationSession(grid, config)
    session.step({"connected": True, "connection_id": 1}, now=0)
    session.set_goal((5, 5))
    assert session.step({"connected": True, "connection_id": 2}, now=1) == (0, 0)
    assert session.status()["goal"] is None


def test_first_connection_does_not_discard_a_queued_goal():
    p = importlib.import_module("mars_rover.planning")
    grid = p.TerrainMap(np.zeros((10, 10)), 1, p.PlanningLimits(robot_radius_m=0))
    config = {
        "schema_version": 1,
        "manifest_sha256": None,
        "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
        "depth": {"camera_id": 4, "to_body": np.eye(4).tolist(), "hfov_deg": 90},
    }
    session = nav().NavigationSession(grid, config)
    session.step({"connected": False, "connection_id": 0}, now=0)
    session.set_goal((5, 5))
    session.step({"connected": True, "connection_id": 1}, now=1)
    assert session.status()["goal"] == (5.0, 5.0)


def test_missing_returns_never_erase_a_previous_hazard():
    p = importlib.import_module("mars_rover.planning")
    grid = p.TerrainMap(np.zeros((20, 20)), 1, p.PlanningLimits(robot_radius_m=0.3))
    grid.observe(np.array([[10, 10, 0.5]]))
    revision = grid.revision
    grid.observe(np.full((100, 3), np.nan))
    assert grid.revision == revision and grid.blocked[10, 10]


def test_observed_obstacle_stops_then_replans_around_the_blocked_route():
    p = importlib.import_module("mars_rover.planning")
    s = importlib.import_module("mars_rover.sensors")
    grid = p.TerrainMap(np.zeros((20, 20)), 1, p.PlanningLimits(robot_radius_m=0))
    config = {
        "schema_version": 1,
        "manifest_sha256": None,
        "source": "test",
        "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
        "depth": {
            "camera_id": 4,
            "hfov_deg": 90,
            "to_body": [[0, 0, 1, 0], [-1, 0, 0, 0], [0, -1, 0, 1], [0, 0, 0, 1]],
        },
    }
    session = nav().NavigationSession(grid, config, min_points=1, settle_s=0)
    session.set_goal((12, 5))

    def capture(frame, points):
        stamp = 1700000000000000000 + frame * 100000000
        status = {
            "connected": True,
            "connection_id": 1,
            "telemetry_age_s": 0,
            "telemetry_unreal": dict(x=-500, y=500, z=0, roll=0, pitch=0, yaw=180, t_ns=str(stamp)),
        }
        depth = np.full((3, 3), np.nan, dtype="float32")
        depth[2, 1] = 150
        session.feed_lidar(s.LidarScan(0, frame, stamp, np.array(points), 1, len(points)), now=frame / 10)
        session.feed_camera(s.CameraFrame(4, frame, stamp, 2, depth), now=frame / 10)
        return status

    status = capture(1, [[2, 0, 0]])
    session.step(status, now=0.1)
    assert session.step(status, now=0.11)[0] > 0
    status = capture(2, [[2, 0, 0], [3, 0, 0.5]])
    assert session.step(status, now=0.2) == (0, 0)
    assert session.status()["state"] == "replanning"
    session.step(status, now=0.21)
    route = session.status()["route"]
    assert session.status()["replans"] == 2
    assert any(y != 5 for x, y in route)
    assert all(grid.segment_clear(a, b) for a, b in zip(route, route[1:]))
