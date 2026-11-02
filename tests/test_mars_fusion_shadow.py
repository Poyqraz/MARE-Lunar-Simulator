"""Observation-only comparison; it must not change navigation decisions."""

import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
import urllib.request

import numpy as np
import pytest

from mars_rover.fusion_shadow import MAX_SAMPLE_POINTS, bounded_sample, compare_sampled_clouds
from mars_rover.navigation import NavigationSession
from mars_rover.nav_service import NavigationService
from mars_rover.planning import PlanningLimits, TerrainMap
from mars_rover.sensors import CameraFrame, LidarScan


def config():
    optical = [[0, 0, 1, 0], [-1, 0, 0, 0], [0, -1, 0, 1], [0, 0, 0, 1]]
    return {"schema_version": 1, "manifest_sha256": None,
            "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
            "depth": {"camera_id": 4, "hfov_deg": 90, "to_body": optical}}


def test_real_categories_are_separate_and_do_not_imply_a_matching_ray():
    lidar = np.array([[1.01, 1.01, 0.2], [2.01, 2.01, -0.2], [3.01, 3.01, 0.2],
                      [4.01, 4.01, 0], [5.01, 5.01, 0.2], [6.01, 6.01, 0.2]])
    depth = np.array([[1.24, 1.24, 0], [2.01, 2.01, 0], [3.01, 3.01, 0.2],
                      [4.01, 4.01, -0.2], [5.01, 5.01, 0], [5.02, 5.02, 0.2],
                      [6.01, 6.01, 0], [6.02, 6.02, 0.1]])
    report = compare_sampled_clouds(lidar, depth, np.zeros((10, 10)), 1, 0.15)
    assert report["shared_bins"] == 6
    assert report["lidar_hazard_depth_ground_like_bins"] == 2
    assert report["lidar_positive_depth_ground_like_bins"] == 1
    assert report["lidar_negative_depth_ground_like_bins"] == 1
    assert report["depth_hazard_lidar_ground_like_bins"] == 1
    assert report["both_sensors_hazard_like_bins"] == 2
    assert "not matching rays" in report["limits"]


def test_unknown_points_and_unseen_bins_never_become_ground_evidence():
    heights = np.zeros((10, 10))
    heights[6:8, 6:8] = np.nan
    lidar = np.array([[1, 1, 0.2], [6.5, 6.5, -0.2], [np.nan, 1, 0], [22, 1, 0]])
    depth = np.array([[2, 2, 0], [6.5, 6.5, 0]])
    report = compare_sampled_clouds(lidar, depth, heights, 1, 0.15)
    assert report["lidar_valid_sample_points"] == 1
    assert report["depth_valid_sample_points"] == 1
    assert report["shared_bins"] == 0
    assert report["lidar_hazard_depth_ground_like_bins"] == 0


def test_cloud_sampling_is_bounded_and_does_not_mutate_input():
    cloud = np.arange(30000 * 3, dtype=float).reshape(-1, 3)
    sample, count = bounded_sample(cloud)
    assert sample.shape == (MAX_SAMPLE_POINTS, 3) and count == 30000
    assert np.array_equal(sample[0], cloud[0]) and np.array_equal(sample[-1], cloud[-1])
    sample[0, 0] = -1
    assert cloud[0, 0] == 0
    with pytest.raises(ValueError, match="sample budget"):
        compare_sampled_clouds(cloud, cloud, np.zeros((10, 10)), 1, 0.15)


def prepare_session(enabled):
    grid = TerrainMap(np.zeros((20, 20)), 1, PlanningLimits(robot_radius_m=0))
    session = NavigationSession(grid, config(), min_points=1, settle_s=0, fusion_shadow=enabled)
    session.set_goal((15, 5))
    stamp = 1700000000000000000
    session.feed_lidar(LidarScan(0, 1, stamp, np.array([[1.5, 0, 0.2]]), 1, 1), now=1.0)
    depth = np.full((3, 3), np.nan, dtype="float32")
    depth[2, 1] = 150
    session.feed_camera(CameraFrame(4, 1, stamp, 2, depth), now=1.0)
    bridge = {"connected": True, "connection_id": 1, "telemetry_age_s": 0,
              "telemetry_unreal": dict(x=-500, y=500, z=0, roll=0, pitch=0, yaw=180, t_ns=str(stamp))}
    return session, bridge


def test_navigation_and_hazard_map_are_identical_with_shadow_on_or_off():
    plain, bridge = prepare_session(False)
    shadow, _ = prepare_session(True)
    assert plain.step(bridge, now=1) == shadow.step(bridge, now=1)
    assert plain.state == shadow.state
    np.testing.assert_array_equal(plain.grid.blocked, shadow.grid.blocked)
    np.testing.assert_array_equal(plain.grid.raw_blocked, shadow.grid.raw_blocked)
    assert plain.motion_deadline() == shadow.motion_deadline()
    assert plain.fusion_shadow_snapshot(now=1.01)["status"] == "disabled"
    observed = shadow.fusion_shadow_snapshot(now=1.01)
    assert observed["status"] == "sampled_comparison"
    assert observed["lidar_hazard_depth_ground_like_bins"] == 1
    assert observed["capture_skew_s"] == 0
    assert observed["depth_source"] == "ground_truth"


def test_shadow_does_not_report_expired_or_mismatched_measurements():
    session, bridge = prepare_session(True)
    session.step(bridge, now=1)
    assert session.fusion_shadow_snapshot(now=1.5)["status"] == "waiting_for_fresh_pose"
    with session.lock:
        session._pose_received_at = session._unique_pose_at = 1.3
        record = session._fusion_frames["ground_truth"]
        record["stamp_ns"] -= 300000000
        session.health["ground_truth"]["stamp_ns"] = record["stamp_ns"]
    assert session.fusion_shadow_snapshot(now=1.3)["status"] == "capture_skew"
    with session.lock:
        session.health.pop("lidar")
    assert session.fusion_shadow_snapshot(now=1.3)["status"] == "waiting_for_fresh_sensor_samples"
    with session.lock:
        session._reset_link()
    assert session.fusion_shadow_snapshot(now=1.3)["status"] == "waiting_for_fresh_pose"


def test_diagnostic_error_does_not_change_obstacle_or_control(monkeypatch):
    import mars_rover.navigation as navigation

    plain, bridge = prepare_session(False)
    shadow, _ = prepare_session(True)

    def fail(_):
        raise RuntimeError("sample failure")

    monkeypatch.setattr(navigation, "bounded_sample", fail)
    assert plain.step(bridge, now=1) == shadow.step(bridge, now=1)
    np.testing.assert_array_equal(plain.grid.blocked, shadow.grid.blocked)
    assert shadow.fusion_shadow_snapshot(now=1.01)["status"] == "diagnostic_error"


def test_comparison_racing_session_reset_is_discarded(monkeypatch):
    import mars_rover.navigation as navigation

    session, bridge = prepare_session(True)
    session.step(bridge, now=1)
    original = navigation.compare_sampled_clouds

    def reset_during_comparison(*args):
        with session.lock:
            session._reset_link()
        return original(*args)

    monkeypatch.setattr(navigation, "compare_sampled_clouds", reset_during_comparison)
    assert session.fusion_shadow_snapshot(now=1.01)["status"] == "samples_invalidated_during_processing"


def test_new_fresh_frame_during_comparison_preserves_the_captured_pair(monkeypatch):
    import mars_rover.navigation as navigation

    session, bridge = prepare_session(True)
    session.step(bridge, now=1)
    stamp = int(bridge["telemetry_unreal"]["t_ns"])
    original = navigation.compare_sampled_clouds

    def receive_new_frame(*args):
        next_stamp = stamp + 100000000
        session.feed_lidar(LidarScan(0, 2, next_stamp, np.array([[1.5, 0, 0.2]]), 1, 1), now=1.1)
        next_bridge = {**bridge, "telemetry_unreal": {**bridge["telemetry_unreal"], "t_ns": str(next_stamp)}}
        session.step(next_bridge, now=1.1)
        return original(*args)

    monkeypatch.setattr(navigation, "compare_sampled_clouds", receive_new_frame)
    result = session.fusion_shadow_snapshot(now=1.11)
    assert result["status"] == "sampled_comparison"
    assert result["newer_frames_during_processing"] is True
    assert result["lidar_stamp_ns"] == str(stamp)  # The result is for the original pair.
    assert result["lidar_arrival_age_s"] == pytest.approx(0.11)
    assert result["lidar_hazard_depth_ground_like_bins"] == 1


def test_invalidated_pair_stays_rejected_even_if_frames_reappear(monkeypatch):
    import mars_rover.navigation as navigation

    session, bridge = prepare_session(True)
    session.step(bridge, now=1)
    original = navigation.compare_sampled_clouds

    def invalidate_then_restore(*args):
        with session.lock:
            saved = dict(session._fusion_frames)
            session.invalidate_fusion()
            session._fusion_frames.update(saved)  # Simulate recovery before computation ends.
        return original(*args)

    monkeypatch.setattr(navigation, "compare_sampled_clouds", invalidate_then_restore)
    assert session.fusion_shadow_snapshot(now=1.01)["status"] == "samples_invalidated_during_processing"


def test_sensor_transport_error_invalidates_inflight_comparisons():
    grid = TerrainMap(np.zeros((10, 10)), 1, PlanningLimits(robot_radius_m=0))
    service = NavigationService(grid, config(), tcp_port=0, bridge_http_port=0, http_port=0,
                                lidar_port=0, camera_port=0, fusion_shadow=True)
    try:
        epoch = service.session._fusion_epoch
        service._sensor_error("lidar", "connection closed")
        assert service.session._fusion_epoch == epoch + 1
        assert service.session._fusion_frames == {}
    finally:
        service.close()


def test_comparison_that_expires_during_processing_is_discarded(monkeypatch):
    import mars_rover.navigation as navigation

    session, bridge = prepare_session(True)
    session.step(bridge, now=1)
    original = navigation.compare_sampled_clouds

    def expire_during_comparison(*args):
        with session.lock:
            session._pose_received_at = 0
        return original(*args)

    monkeypatch.setattr(navigation, "compare_sampled_clouds", expire_during_comparison)
    assert session.fusion_shadow_snapshot(now=1.01)["status"] == "samples_expired_during_processing"


def test_optional_endpoint_is_read_only_and_disabled_by_default():
    grid = TerrainMap(np.zeros((10, 10)), 1, PlanningLimits(robot_radius_m=0))
    with NavigationService(grid, config(), tcp_port=0, bridge_http_port=0, http_port=0,
                           lidar_port=0, camera_port=0) as service:
        before = grid.blocked.copy()
        url = f"http://127.0.0.1:{service.http.server_port}/dashboard/fusion-shadow"
        with urllib.request.urlopen(url, timeout=3) as response:
            assert json.load(response) == {"enabled": False, "status": "disabled"}
        np.testing.assert_array_equal(grid.blocked, before)


def test_enabled_http_endpoint_compares_actual_session_inputs():
    grid = TerrainMap(np.zeros((20, 20)), 1, PlanningLimits(robot_radius_m=0))
    service = NavigationService(grid, config(), tcp_port=0, bridge_http_port=0, http_port=0,
                                lidar_port=0, camera_port=0, min_points=1, settle_s=0, fusion_shadow=True)
    try:
        now = time.monotonic()
        stamp = 1700000000000000000
        service.session.feed_lidar(LidarScan(0, 1, stamp, np.array([[1.5, 0, 0.2]]), 1, 1), now=now)
        depth = np.full((3, 3), np.nan, dtype="float32")
        depth[2, 1] = 150
        service.session.feed_camera(CameraFrame(4, 1, stamp, 2, depth), now=now)
        bridge = {"connected": True, "connection_id": 1, "telemetry_age_s": 0,
                  "telemetry_unreal": dict(x=-500, y=500, z=0, roll=0, pitch=0, yaw=180, t_ns=str(stamp))}
        service.session.step(bridge, now=now)
        before = grid.blocked.copy()
        thread = threading.Thread(target=service.http.handle_request, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{service.http.server_port}/dashboard/fusion-shadow"
        with urllib.request.urlopen(url, timeout=3) as response:
            value = json.load(response)
        thread.join(timeout=3)
        assert value["status"] == "sampled_comparison"
        assert value["lidar_hazard_depth_ground_like_bins"] == 1
        np.testing.assert_array_equal(grid.blocked, before)
    finally:
        service.close()


def test_http_comparison_survives_a_new_sensor_frame_while_processing(monkeypatch):
    import mars_rover.navigation as navigation

    grid = TerrainMap(np.zeros((20, 20)), 1, PlanningLimits(robot_radius_m=0))
    service = NavigationService(grid, config(), tcp_port=0, bridge_http_port=0, http_port=0,
                                lidar_port=0, camera_port=0, min_points=1, settle_s=0, fusion_shadow=True)
    started, release, replies, failures = threading.Event(), threading.Event(), [], []
    try:
        now = time.monotonic()
        stamp = 1700000000000000000
        service.session.feed_lidar(LidarScan(0, 1, stamp, np.array([[1.5, 0, 0.2]]), 1, 1), now=now)
        depth = np.full((3, 3), np.nan, dtype="float32")
        depth[2, 1] = 150
        service.session.feed_camera(CameraFrame(4, 1, stamp, 2, depth), now=now)
        bridge = {"connected": True, "connection_id": 1, "telemetry_age_s": 0,
                  "telemetry_unreal": dict(x=-500, y=500, z=0, roll=0, pitch=0, yaw=180, t_ns=str(stamp))}
        service.session.step(bridge, now=now)
        original = navigation.compare_sampled_clouds

        def delayed(*args):
            started.set()
            assert release.wait(2)
            return original(*args)

        monkeypatch.setattr(navigation, "compare_sampled_clouds", delayed)
        server = threading.Thread(target=service.http.handle_request, daemon=True)
        server.start()
        url = f"http://127.0.0.1:{service.http.server_port}/dashboard/fusion-shadow"

        def request():
            try:
                with urllib.request.urlopen(url, timeout=3) as response:
                    replies.append(json.load(response))
            except Exception as error:
                failures.append(error)

        client = threading.Thread(target=request, daemon=True)
        client.start()
        assert started.wait(2)
        later = time.monotonic()
        next_stamp = stamp + 33333333
        service.session.feed_lidar(LidarScan(0, 2, next_stamp, np.array([[1.5, 0, 0.2]]), 1, 1), now=later)
        next_bridge = {**bridge, "telemetry_unreal": {**bridge["telemetry_unreal"], "t_ns": str(next_stamp)}}
        service.session.step(next_bridge, now=later)
        release.set()
        client.join(timeout=3)
        server.join(timeout=3)
        assert not failures and not client.is_alive()
        assert replies[0]["status"] == "sampled_comparison"
        assert replies[0]["newer_frames_during_processing"] is True
        assert replies[0]["lidar_stamp_ns"] == str(stamp)
    finally:
        release.set()
        service.close()


def test_dashboard_displays_shadow_status_and_loss():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed for the dashboard behavior test")
    script = Path(__file__).parent / "js" / "dashboard_fusion_shadow.js"
    subprocess.run([node, str(script)], check=True, capture_output=True, text=True, timeout=10)


def test_cli_enables_shadow_explicitly(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from mars_rover import nav_service

    config_path = tmp_path / "sensor.json"
    config_path.write_text("{}", encoding="utf-8")
    seen = {}

    class FakeService:
        def __init__(self, grid, settings, **kwargs):
            seen.update(kwargs)
            self.ending = SimpleNamespace(wait=lambda timeout: True)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(nav_service.TerrainMap, "from_bundle", lambda path: object())
    monkeypatch.setattr(nav_service, "NavigationService", FakeService)
    nav_service.main(["--sensors", str(config_path), "--fusion-shadow"])
    assert seen["fusion_shadow"] is True
