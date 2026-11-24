import math
import json
import urllib.request

import numpy as np
import pytest

from mars_rover.navigation import NavigationSession
from mars_rover.nav_service import NavigationService
from mars_rover.planning import PlanningLimits, TerrainMap
from mars_rover.sensors import CameraFrame, LidarScan


def test_optional_shortcut_removes_extra_grid_corners_only_when_enabled():
    grid = TerrainMap(np.zeros((15, 15)), 1, PlanningLimits(robot_radius_m=0.6))
    start, goal = (5.2, 5.0), (6.1, 3.2)
    original = grid.plan(start, goal)
    before = grid.blocked.copy()
    direct = grid.plan(start, goal, prefer_short_direct=True)
    assert len(original) > 2
    assert direct == [start, goal]
    assert grid.segment_clear(*direct)
    assert grid._sampled_route_profile(direct)[0] < grid._sampled_route_profile(original)[0]
    assert np.array_equal(grid.blocked, before) and grid.revision == 0
    # The experiment does not change the default planning policy.
    assert grid.plan(start, goal) == original


@pytest.mark.parametrize("source", ["observed_hazard", "unknown"])
def test_shortcut_does_not_cross_observed_or_unknown_cells(source):
    heights = np.zeros((16, 16))
    valid = np.ones_like(heights, dtype=bool)
    if source == "unknown":
        valid[6, 7] = False
    grid = TerrainMap(heights, 1, PlanningLimits(robot_radius_m=0.6), valid=valid)
    if source == "observed_hazard":
        grid.observe(np.array([[7, 6, 0.3]]))
    start, goal = (3., 6.), (11., 6.)
    assert not grid.segment_clear(start, goal)
    route = grid.plan(start, goal, prefer_short_direct=True)
    assert len(route) > 2 and all(grid.segment_clear(a, b) for a, b in zip(route, route[1:]))
    assert grid.blocked[6, 7]


def test_shortcut_does_not_prefer_a_higher_sampled_terrain_cost():
    heights = np.zeros((16, 16))
    heights[6, 5:9] = 0.15
    grid = TerrainMap(heights, 1, PlanningLimits(robot_radius_m=0))
    start, goal = (3., 6.), (10., 6.)
    original = grid.plan(start, goal)
    assert grid.segment_clear(start, goal)
    assert grid._sampled_route_profile([start, goal])[0] > grid._sampled_route_profile(original)[0]
    assert grid.plan(start, goal, prefer_short_direct=True) == original


def test_shortcut_can_trade_a_higher_allowed_peak_for_lower_sampled_terrain_cost():
    heights = np.zeros((16, 16))
    heights[6, 9], heights[8, 9], heights[8, 10] = 0.103575, -0.059661, 0.04452
    grid = TerrainMap(heights, 1, PlanningLimits(robot_radius_m=0))
    start, goal = (3.2, 5.2), (10.2, 7.8)
    original = grid.plan(start, goal)
    old_cost, old_slope = grid._sampled_route_profile(original)
    direct_cost, direct_slope = grid._sampled_route_profile([start, goal])
    assert grid.segment_clear(start, goal)
    assert direct_cost < old_cost and direct_slope > old_slope
    assert direct_slope < grid.limits.max_slope_deg
    assert grid.plan(start, goal, prefer_short_direct=True) == [start, goal]


def test_long_routes_and_invalid_option_are_not_silently_changed():
    grid = TerrainMap(np.zeros((18, 18)), 1, PlanningLimits(robot_radius_m=0))
    start, goal = (3., 5.), (12., 6.)
    assert math.dist(start, goal) > 8
    assert grid.plan(start, goal, prefer_short_direct=True) == grid.plan(start, goal)
    with pytest.raises(ValueError, match="boolean"):
        grid.plan(start, goal, prefer_short_direct=1)


def test_shortcut_still_stops_and_replans_for_a_new_obstacle():
    grid = TerrainMap(np.zeros((20, 20)), 1, PlanningLimits(robot_radius_m=0))
    optical = [[0, 0, 1, 0], [-1, 0, 0, 0], [0, -1, 0, 1], [0, 0, 0, 1]]
    config = {"schema_version": 1, "manifest_sha256": None,
              "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
              "depth": {"camera_id": 4, "hfov_deg": 90, "to_body": optical}}
    session = NavigationSession(grid, config, min_points=1, settle_s=0, prefer_short_direct=True)
    session.set_goal((12, 5))

    def capture(frame, points):
        stamp = 1700000000000000000 + frame * 100000000
        status = {"connected": True, "connection_id": 1, "telemetry_age_s": 0,
                  "telemetry_unreal": dict(x=-500, y=500, z=0, roll=0, pitch=0, yaw=180, t_ns=str(stamp))}
        depth = np.full((3, 3), np.nan, dtype="float32")
        depth[2, 1] = 150
        session.feed_lidar(LidarScan(0, frame, stamp, np.array(points), 1, len(points)), now=frame / 10)
        session.feed_camera(CameraFrame(4, frame, stamp, 2, depth), now=frame / 10)
        return status

    status = capture(1, [[2, 0, 0]])
    session.step(status, now=0.1)
    assert session.status()["route"] == [(5., 5.), (12., 5.)]
    assert session.step(status, now=0.11)[0] > 0
    assert session.mission_snapshot(now=0.11)["short_direct_route_enabled"] is True
    assert session.mission_export()["short_direct_route_enabled"] is True
    status = capture(2, [[2, 0, 0], [3, 0, 0.5]])
    assert session.step(status, now=0.2) == (0, 0)
    assert session.status()["state"] == "replanning"
    session.step(status, now=0.21)
    route = session.status()["route"]
    assert session.status()["replans"] == 2
    assert any(y != 5 for x, y in route)
    assert all(grid.segment_clear(a, b) for a, b in zip(route, route[1:]))


@pytest.mark.parametrize("enabled", [False, True])
def test_service_reports_the_actual_short_direct_setting(enabled):
    grid = TerrainMap(np.zeros((10, 10)), 1, PlanningLimits(robot_radius_m=0))
    config = {"schema_version": 1, "manifest_sha256": None,
              "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
              "depth": {"camera_id": 4, "hfov_deg": 90, "to_body": np.eye(4).tolist()}}
    with NavigationService(grid, config, tcp_port=0, bridge_http_port=0, http_port=0,
                           lidar_port=0, camera_port=0, prefer_short_direct=enabled) as service:
        base = f"http://127.0.0.1:{service.http.server_port}"
        for path in ("/status", "/mission/snapshot", "/mission/export"):
            with urllib.request.urlopen(base + path, timeout=3) as response:
                assert json.load(response)["short_direct_route_enabled"] is enabled


def test_cli_enables_the_preference_only_when_requested(monkeypatch, tmp_path):
    import mars_rover.nav_service as module

    sensors = tmp_path / "sensors.json"
    sensors.write_text("{}", encoding="utf-8")
    observed = []

    class FakeService:
        def __init__(self, *_args, **kwargs):
            observed.append(kwargs["prefer_short_direct"])
            self.ending = type("Stop", (), {"wait": lambda _self, _seconds: True})()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr(module, "NavigationService", FakeService)
    monkeypatch.setattr(module.TerrainMap, "from_bundle", lambda _manifest: object())
    module.main(["--sensors", str(sensors)])
    module.main(["--sensors", str(sensors), "--prefer-short-direct"])
    assert observed == [False, True]
