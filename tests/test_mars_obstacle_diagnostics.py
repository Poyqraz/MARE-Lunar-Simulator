"""Obstacle provenance is optional, bounded and does not change driving decisions."""

import json
import urllib.request

import numpy as np
import pytest

from mars_rover.navigation import NavigationSession
from mars_rover.nav_service import NavigationService
from mars_rover.planning import PlanningLimits, TerrainMap
from mars_rover.sensors import CameraFrame, LidarScan


def test_obstacle_diagnostics_preserve_grid_decisions_and_record_new_cells():
    plain = TerrainMap(np.zeros((20, 20)), 1, PlanningLimits(robot_radius_m=0.6))
    traced = TerrainMap(np.zeros((20, 20)), 1, PlanningLimits(robot_radius_m=0.6))
    points = np.array([[8.1, 5.1, 0.4], [8.2, 5.2, 0.6], [9.1, 6.1, -0.5], [7, 5, 0]])

    normal = plain.observe(points)
    report = traced.observe(points, diagnostics=True)
    details = report.pop("diagnostics")
    assert report == normal
    np.testing.assert_array_equal(traced.blocked, plain.blocked)
    assert details["new_cells_total"] == 2
    cells = {tuple(c["cell_row_col"]): c for c in details["new_cells"]}
    assert cells[5, 8]["hazard_points"] == 2
    assert cells[5, 8]["sample_world_m"] == pytest.approx([8.1, 5.1, 0.4])
    assert cells[5, 8]["sample_residual_m"] == pytest.approx(0.4)
    assert cells[6, 9]["sample_residual_m"] == pytest.approx(-0.5)

    repeated = traced.observe(points, diagnostics=True)
    assert not repeated["map_changed"]
    assert repeated["diagnostics"]["new_cells_total"] == 0


def test_obstacle_diagnostics_limit_is_explicit():
    grid = TerrainMap(np.zeros((22, 22)), 1, PlanningLimits(robot_radius_m=0))
    points = np.array([[x, y, 0.3] for y in range(1, 21) for x in range(1, 21)])
    details = grid.observe(points, diagnostics=True)["diagnostics"]
    assert details["new_cells_total"] == 400
    assert len(details["new_cells"]) == 256
    assert details["new_cells_truncated"] == 144
    assert grid.raw_blocked[20, 20]


def test_bounded_diagnostics_prioritize_cells_near_rover_and_goal():
    grid = TerrainMap(np.zeros((22, 22)), 1, PlanningLimits(robot_radius_m=0))
    points = np.array([[x, y, 0.3] for y in range(1, 21) for x in range(1, 21)])
    details = grid.observe(points, diagnostics=True, diagnostic_focus=((1, 1), (20, 20)))["diagnostics"]
    cells = [c["cell_row_col"] for c in details["new_cells"]]
    assert [1, 1] in cells and [20, 20] in cells
    assert details["new_cells_truncated"] == 144


@pytest.mark.parametrize("radius", [0.0, 0.3, 0.6, 1.7])
def test_endpoint_contributors_match_the_existing_inflation_rule(radius):
    grid = TerrainMap(np.zeros((14, 14)), 1, PlanningLimits(robot_radius_m=radius))
    grid.observe(np.array([[3, 4, 0.4], [9, 10, -0.4]]))
    for row in range(14):
        for col in range(14):
            detail = grid.blockage_details((col, row))
            assert detail["blocked"] == bool(detail["contributors_raw_row_col"])
            assert detail["raw_blocked"] == bool(grid.raw_blocked[row, col])


def test_diagnostic_collection_failure_does_not_undo_the_obstacle(monkeypatch):
    grid = TerrainMap(np.zeros((10, 10)), 1, PlanningLimits(robot_radius_m=0))

    def fail(*args, **kwargs):
        raise RuntimeError("diagnostic failure")

    monkeypatch.setattr(np, "unique", fail)
    report = grid.observe(np.array([[4, 4, 0.5]]), diagnostics=True)
    assert report["map_changed"] and grid.blocked[4, 4]
    assert report["diagnostics"]["collection_error"] == "diagnostic failure"


def test_start_block_is_traced_to_actual_lidar_observation_without_commanding_through_it():
    grid = TerrainMap(np.zeros((20, 20)), 1, PlanningLimits(robot_radius_m=0.6))
    config = {
        "schema_version": 1,
        "manifest_sha256": None,
        "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
        "depth": {"camera_id": 4, "hfov_deg": 90,
                  "to_body": [[0, 0, 1, 0], [-1, 0, 0, 0], [0, -1, 0, 1], [0, 0, 0, 1]]},
    }
    session = NavigationSession(grid, config, min_points=1, settle_s=0, obstacle_diagnostics=True)
    session.set_goal((12, 5))

    def feed(frame, points):
        stamp = 1700000000000000000 + frame * 100000000
        status = {"connected": True, "connection_id": 1, "telemetry_age_s": 0,
                  "telemetry_unreal": dict(x=-500, y=500, z=0, roll=0, pitch=0, yaw=180, t_ns=str(stamp))}
        session.feed_lidar(LidarScan(0, frame, stamp, np.array(points), 1, len(points)), now=frame / 10)
        depth = np.full((3, 3), np.nan, dtype="float32")
        depth[2, 1] = 150
        session.feed_camera(CameraFrame(4, frame, stamp, 2, depth), now=frame / 10)
        return status

    status = feed(1, [[2, 0, 0]])
    assert session.step(status, now=0.1) == (0, 0)
    assert session.step(status, now=0.11)[0] > 0
    status = feed(2, [[2, 0, 0], [0.1, 0, 0.4]])
    assert session.step(status, now=0.2) == (0, 0)
    assert session.state == "replanning"
    assert session.step(status, now=0.21) == (0, 0)
    assert session.state == "blocked"

    export = session.mission_export()
    diag = export["obstacle_diagnostics"]
    assert diag["frames_evicted"] == 0
    frame = diag["frames"][-1]
    assert frame["source"] == "lidar"
    assert frame["stamp_ns"] == "1700000000200000000"
    assert frame["map_revision"] == grid.revision
    assert frame["new_cells"][0]["cell_row_col"] == [5, 5]
    assert frame["new_cells"][0]["sample_residual_m"] == pytest.approx(0.4)
    assert diag["last_planning_failure"]["start"]["blocked"] is True
    assert diag["last_planning_failure"]["goal"]["blocked"] is False
    assert [5, 5] in diag["last_planning_failure"]["start"]["contributors_raw_row_col"]
    json.dumps(export, allow_nan=False)


def test_depth_observation_is_attributed_to_depth_not_lidar():
    grid = TerrainMap(np.zeros((20, 20)), 1, PlanningLimits(robot_radius_m=0.6))
    config = {
        "schema_version": 1, "manifest_sha256": None,
        "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
        "depth": {"camera_id": 4, "hfov_deg": 90,
                  "to_body": [[0, 0, 1, 0], [-1, 0, 0, 0], [0, -1, 0, 1], [0, 0, 0, 1]]},
    }
    session = NavigationSession(grid, config, min_points=1, settle_s=0, obstacle_diagnostics=True)
    stamp = 1700000000100000000
    status = {"connected": True, "connection_id": 1, "telemetry_age_s": 0,
              "telemetry_unreal": dict(x=-500, y=500, z=0, roll=0, pitch=0, yaw=180, t_ns=str(stamp))}
    session.feed_lidar(LidarScan(0, 1, stamp, np.array([[2, 0, 0]]), 1, 1), now=0.1)
    depth = np.full((3, 3), np.nan, dtype="float32")
    depth[1, 1] = 100  # An elevated point in the optical center.
    session.feed_camera(CameraFrame(4, 1, stamp, 2, depth), now=0.1)
    session.step(status, now=0.1)
    frames = session.mission_export()["obstacle_diagnostics"]["frames"]
    assert len(frames) == 1 and frames[0]["source"] == "ground_truth"
    assert frames[0]["new_cells"][0]["cell_row_col"] == [5, 6]


def test_disabled_diagnostics_leave_export_unchanged():
    grid = TerrainMap(np.zeros((10, 10)), 1, PlanningLimits(robot_radius_m=0))
    config = {"schema_version": 1, "manifest_sha256": None,
              "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
              "depth": {"camera_id": 4, "hfov_deg": 90, "to_body": np.eye(4).tolist()}}
    session = NavigationSession(grid, config)
    assert "obstacle_diagnostics" not in session.mission_export()


def test_diagnostics_are_available_via_the_actual_read_only_mission_export():
    grid = TerrainMap(np.zeros((20, 20)), 1, PlanningLimits(robot_radius_m=0))
    config = {"schema_version": 1, "manifest_sha256": None,
              "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
              "depth": {"camera_id": 4, "hfov_deg": 90, "to_body": np.eye(4).tolist()}}
    with NavigationService(grid, config, tcp_port=0, bridge_http_port=0, http_port=0,
                           lidar_port=0, camera_port=0, obstacle_diagnostics=True) as service:
        stamp = 1700000000100000000
        with service.session.lock:
            service.session.feed_lidar(LidarScan(0, 1, stamp, np.array([[2, 0, 0.5]]), 1, 1), now=1)
            status = {"connected": True, "connection_id": 1, "telemetry_age_s": 0,
                      "telemetry_unreal": dict(x=-500, y=500, z=0, roll=0, pitch=0,
                                               yaw=180, t_ns=str(stamp))}
            assert service.session.step(status, now=1) == (0, 0)
        url = f"http://127.0.0.1:{service.http.server_port}/mission/export"
        with urllib.request.urlopen(url, timeout=3) as response:
            export = json.load(response)
        assert export["obstacle_diagnostics"]["frames"][0]["source"] == "lidar"
        assert export["obstacle_diagnostics"]["frames"][0]["new_cells"][0]["cell_row_col"] == [5, 7]
