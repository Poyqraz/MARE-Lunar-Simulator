"""The viewer exposes the real planner mask without changing its decisions."""

import base64
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request

import numpy as np
import pytest

from mars_rover.nav_service import NavigationService
from mars_rover.planning import PlanningLimits, TerrainMap


def config():
    return {"schema_version": 1, "manifest_sha256": None,
            "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
            "depth": {"camera_id": 4, "hfov_deg": 90, "to_body": np.eye(4).tolist()}}


def test_actual_http_grid_matches_planner_and_keeps_first_source():
    grid = TerrainMap(np.zeros((16, 16)), 1, PlanningLimits(robot_radius_m=0.6))
    baseline = grid.static_raw_blocked.copy()
    grid.observe(np.array([[5., 5., 0.3]]), source="lidar")
    revision = grid.revision
    # A later sensor is corroborating evidence, not a change of first source.
    grid.observe(np.array([[5., 5., 0.3]]), source="ground_truth")
    assert grid.revision == revision
    grid.observe(np.array([[9., 8., -0.3]]), source="ground_truth")
    grid.observe(np.array([[12., 10., 0.3]]), source="stereo")
    grid.observe(np.array([[5., 10., 0.3]]))
    with NavigationService(grid, config(), tcp_port=0, bridge_http_port=0, http_port=0,
                           lidar_port=0, camera_port=0) as service:
        before = grid.blocked.copy()
        url = f"http://127.0.0.1:{service.http.server_port}/dashboard/occupancy"
        with urllib.request.urlopen(url, timeout=3) as response:
            reply = json.load(response)
        cells = np.frombuffer(base64.b64decode(reply["classes_b64"], validate=True), np.uint8).reshape(16, 16)
        assert reply["session_id"] == service.session.mission.session_id
        assert reply["revision"] == grid.revision
        assert reply["resolution"] == 1
        np.testing.assert_array_equal(cells != 0, grid.blocked)
        np.testing.assert_array_equal(grid.static_raw_blocked, baseline)
        np.testing.assert_array_equal(grid.blocked, before)
        assert cells[0, 0] == 1                 # Terrain/validity prior.
        assert cells[5, 5] == 2                 # LiDAR first.
        assert cells[8, 9] == 3                 # Ground truth depth first.
        assert cells[10, 12] == 4               # Stereo first.
        assert cells[10, 5] == 5                # Unspecified source.
        assert cells[5, 6] == 6                 # Inflated footprint margin.
        assert cells[3, 3] == 0


def test_provenance_never_changes_existing_occupancy_or_route():
    limits = PlanningLimits(robot_radius_m=0.6)
    default = TerrainMap(np.zeros((16, 16)), 1, limits)
    with_source = TerrainMap(np.zeros((16, 16)), 1, limits)
    points = np.array([[5.1, 5.1, 0.3], [9.1, 8.1, -0.4], [7, 7, 0]])
    assert default.observe(points) == with_source.observe(points, source="lidar")
    np.testing.assert_array_equal(default.blocked, with_source.blocked)
    assert default.plan((3, 3), (12, 12)) == with_source.plan((3, 3), (12, 12))
    with pytest.raises(ValueError, match="Unknown observation source"):
        with_source.observe(points, source="other")
    np.testing.assert_array_equal(default.blocked, with_source.blocked)


def test_navigation_sensor_inputs_set_the_first_source():
    from mars_rover.sensors import CameraFrame, LidarScan

    grid = TerrainMap(np.zeros((20, 20)), 1, PlanningLimits(robot_radius_m=0))
    settings = config()
    settings["depth"]["to_body"] = [[0, 0, 1, 0], [-1, 0, 0, 0], [0, -1, 0, 1], [0, 0, 0, 1]]
    with NavigationService(grid, settings, tcp_port=0, bridge_http_port=0, http_port=0,
                           lidar_port=0, camera_port=0) as service:
        stamp = 1700000000100000000
        session = service.session
        session.feed_lidar(LidarScan(0, 1, stamp, np.array([[2., 0., 0.5]]), 1, 1), now=1)
        depth = np.full((3, 3), np.nan, dtype="float32")
        depth[1, 1] = 100
        session.feed_camera(CameraFrame(4, 1, stamp, 2, depth), now=1)
        status = {"connected": True, "connection_id": 1, "telemetry_age_s": 0,
                  "telemetry_unreal": dict(x=-500, y=500, z=0, roll=0, pitch=0, yaw=180, t_ns=str(stamp))}
        session.step(status, now=1)
        assert grid.first_sensor_source[5, 7] == 1
        assert grid.first_sensor_source[5, 6] == 2


def test_actual_javascript_updates_and_invalidates_the_grid():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed for the dashboard behavior test")
    script = Path(__file__).parent / "js" / "dashboard_planner_grid.js"
    subprocess.run([node, str(script)], check=True, capture_output=True, text=True, timeout=10)
