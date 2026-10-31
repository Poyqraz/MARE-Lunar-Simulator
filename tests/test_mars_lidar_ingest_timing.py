"""Capture timing around LiDAR delivery without weakening navigation gates."""

import json
import threading
import time
from types import SimpleNamespace
import urllib.request

import numpy as np
import pytest

from mars_rover.nav_service import NavigationService
from mars_rover.planning import PlanningLimits, TerrainMap
from mars_rover.sensors import LidarScan


def service(*, diagnostics=True):
    config = {"schema_version": 1, "manifest_sha256": None,
              "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
              "depth": {"camera_id": 4, "hfov_deg": 90, "to_body": np.eye(4).tolist()}}
    return NavigationService(TerrainMap(np.zeros((10, 10)), 1, PlanningLimits(robot_radius_m=0)),
                             config, tcp_port=0, bridge_http_port=0, http_port=0,
                             lidar_port=0, camera_port=0, obstacle_diagnostics=diagnostics)


def test_lidar_timing_separates_capture_lag_from_session_feed_delay(monkeypatch):
    import mars_rover.nav_service as module

    clock = SimpleNamespace(value=100.0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.value))
    nav = service()
    stamp = 1700000000000000000
    nav.bridge.telemetry = {"t_ns": str(stamp + 100_000_000)}
    nav.bridge.telemetry_received_at = 99.99
    nav.bridge.connection_id = 3
    nav.bridge.state.connect()
    observed = []

    def blocked_feed(scan, *, now):
        observed.append(now)
        clock.value += 0.25
        nav.bridge.telemetry = {"t_ns": str(stamp + 350_000_000)}
        nav.bridge.telemetry_received_at = 100.24

    monkeypatch.setattr(nav.session, "feed_lidar", blocked_feed)
    try:
        nav._lidar_received(LidarScan(0, 7, stamp, np.zeros((1, 3)), 1, 1))
        sample = nav.lidar_ingest_timing()["samples"][-1]
        assert observed == [100.0]
        assert sample["frame_id"] == 7
        assert sample["lidar_stamp_ns"] == str(stamp)
        assert sample["capture_lag_before_s"] == pytest.approx(0.1)
        assert sample["capture_lag_after_s"] == pytest.approx(0.35)
        assert sample["session_feed_s"] == pytest.approx(0.25)
        assert sample["pose_reference_s"] == pytest.approx(0.0)
        assert sample["pose_before_age_s"] == pytest.approx(0.01)
        assert sample["pose_after_age_s"] == pytest.approx(0.01)
        assert sample["connection_id_before"] == sample["connection_id_after"] == 3
        json.dumps(nav.lidar_ingest_timing(), allow_nan=False)
    finally:
        nav.close()


def test_failed_pose_diagnostics_do_not_discard_the_lidar_scan(monkeypatch):
    nav = service()
    scan = LidarScan(0, 1, 1700000000000000000, np.zeros((1, 3)), 1, 1)

    def fail():
        raise RuntimeError("diagnostic reference failed")

    monkeypatch.setattr(nav, "_pose_reference", fail)
    try:
        nav._lidar_received(scan)
        assert nav.session.latest["lidar"][0] is scan
        assert nav.feeds.scan[0] is scan
        sample = nav.lidar_ingest_timing()["samples"][-1]
        assert sample["capture_lag_before_s"] is None
        assert "diagnostic reference failed" in sample["pose_before_error"]
    finally:
        nav.close()


def test_recorded_feed_duration_includes_real_session_lock_wait(monkeypatch):
    nav = service()
    started = threading.Event()
    scan = LidarScan(0, 1, 1700000000000000000, np.zeros((1, 3)), 1, 1)
    reference = nav._safe_pose_reference

    def signal_reference():
        result = reference()
        started.set()
        return result

    monkeypatch.setattr(nav, "_safe_pose_reference", signal_reference)

    def deliver():
        nav._lidar_received(scan)

    worker = threading.Thread(target=deliver)
    try:
        with nav.session.lock:
            worker.start()
            assert started.wait(timeout=1)
            time.sleep(0.06)
            assert worker.is_alive()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert nav.lidar_ingest_timing()["samples"][-1]["session_feed_s"] >= 0.03
    finally:
        worker.join(timeout=2)
        nav.close()


def test_missing_pose_is_not_fabricated_and_samples_are_bounded():
    nav = service()
    try:
        for i in range(20):
            nav._lidar_received(LidarScan(0, i, 1700000000000000000 + i, np.zeros((1, 3)), 1, 1))
        result = nav.lidar_ingest_timing()
        assert len(result["samples"]) == result["max_samples"] == 16
        assert result["samples_evicted"] == 4
        assert result["samples"][0]["frame_id"] == 4
        assert result["samples"][-1]["capture_lag_before_s"] is None
        assert result["samples"][-1]["pose_before_age_s"] is None
    finally:
        nav.close()


def test_lidar_timing_is_exported_over_http_only_when_enabled():
    with service() as nav:
        nav._lidar_received(LidarScan(0, 1, 1700000000000000000, np.zeros((1, 3)), 1, 1))
        base = f"http://127.0.0.1:{nav.http.server_port}"
        for path in ("/status", "/mission/snapshot", "/mission/export"):
            with urllib.request.urlopen(base + path, timeout=3) as response:
                result = json.load(response)
            assert result["lidar_ingest_timing"]["samples"][-1]["frame_id"] == 1
    with service(diagnostics=False) as nav:
        nav._lidar_received(LidarScan(0, 1, 1700000000000000000, np.zeros((1, 3)), 1, 1))
        with urllib.request.urlopen(f"http://127.0.0.1:{nav.http.server_port}/status", timeout=3) as response:
            assert "lidar_ingest_timing" not in json.load(response)
