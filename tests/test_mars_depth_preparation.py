"""Ground-truth depth preparation must not hold the navigation session lock."""

import threading
from types import SimpleNamespace

import numpy as np

from mars_rover.navigation import NavigationSession
from mars_rover.planning import PlanningLimits, TerrainMap
from mars_rover.sensors import CameraFrame, LidarScan, depth_points


def make_session():
    grid = TerrainMap(np.zeros((20, 20)), 1, PlanningLimits(robot_radius_m=0))
    config = {"schema_version": 1, "manifest_sha256": None,
              "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
              "depth": {"camera_id": 4, "hfov_deg": 90,
                        "to_body": [[0, 0, 1, 0], [-1, 0, 0, 0], [0, -1, 0, 1], [0, 0, 0, 1]]}}
    return NavigationSession(grid, config, min_points=1, settle_s=0)


def test_depth_preparation_does_not_block_lidar_ingress(monkeypatch):
    import mars_rover.navigation as module

    session = make_session()
    prepare_started, release, lidar_received = threading.Event(), threading.Event(), threading.Event()
    original = module.depth_points

    def slow_preparation(*args, **kwargs):
        prepare_started.set()
        assert release.wait(timeout=2)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "depth_points", slow_preparation)
    stamp = 1700000000000000000
    frame = CameraFrame(4, 1, stamp, 2, np.full((3, 3), 100, dtype=np.float32))
    camera = threading.Thread(target=session.feed_camera, args=(frame,), kwargs={"now": 1.0})

    def send_lidar():
        session.feed_lidar(LidarScan(0, 1, stamp, np.array([[1.0, 0, 0]]), 1, 1), now=1.0)
        lidar_received.set()

    camera.start()
    lidar = None
    try:
        assert prepare_started.wait(timeout=1)
        lidar = threading.Thread(target=send_lidar)
        lidar.start()
        assert lidar_received.wait(timeout=1), "LiDAR waited for depth projection"
    finally:
        release.set()
        camera.join(timeout=2)
        if lidar:
            lidar.join(timeout=2)
    assert session.latest["lidar"][0].frame_id == 1


def test_ground_truth_preparation_keeps_all_original_in_range_points():
    session = make_session()
    pixels = np.array([[100, 200, np.nan, 900], [0, 250, 300, np.inf], [400, 500, -1, 800]], dtype=np.float32)
    frame = CameraFrame(4, 2, 1700000000000000000, 2, pixels)
    expected = depth_points(frame.depth_m(), hfov_deg=90)
    expected = expected[np.isfinite(expected).all(axis=1) & (np.linalg.norm(expected, axis=1) <= 8)]
    session.feed_camera(frame, now=1.0)
    prepared, received = session.latest["ground_truth"]
    np.testing.assert_array_equal(prepared.points, expected)
    assert received == 1.0
    assert prepared.stamp_ns == frame.stamp_ns


def test_preparation_time_counts_towards_freshness_and_cannot_start_motion(monkeypatch):
    import mars_rover.navigation as module

    session = make_session()
    clock = SimpleNamespace(value=100.0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.value))
    original = module.depth_points

    def slow_preparation(*args, **kwargs):
        clock.value += 0.41
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "depth_points", slow_preparation)
    stamp = 1700000000000000000
    depth = np.full((3, 3), np.nan, dtype=np.float32)
    depth[2, 1] = 150
    session.feed_camera(CameraFrame(4, 1, stamp, 2, depth))
    assert session.latest["ground_truth"][1] == 100.0
    session.feed_lidar(LidarScan(0, 1, stamp, np.array([[2.0, 0, 0]]), 1, 1), now=clock.value)
    session.set_goal((10, 5))
    status = {"connected": True, "connection_id": 1, "telemetry_age_s": 0,
              "telemetry_unreal": dict(x=-500, y=500, z=0, roll=0, pitch=0, yaw=180, t_ns=str(stamp))}
    assert session.step(status, now=clock.value) == (0, 0)
    assert session.state == "waiting_for_sensors"
    assert "arrival_stale" in session.sensor_wait_details["ground_truth"]["reasons"]


def _posed_session(stamp):
    session = make_session()
    status = {"connected": True, "connection_id": 1, "telemetry_age_s": 0,
              "telemetry_unreal": dict(x=-500, y=500, z=0, roll=0, pitch=0, yaw=180, t_ns=str(stamp))}
    session.step(status, now=1.0)
    return session


def test_depth_classification_runs_outside_the_session_lock(monkeypatch):
    stamp = 1700000000000000000
    session = _posed_session(stamp)
    original, lock_free = session.grid.classify, []

    def classify(points):
        probe = threading.Thread(target=lambda: lock_free.append(session.lock.acquire(timeout=0.5)
                                                                 and (session.lock.release() or True)))
        probe.start()
        probe.join()
        return original(points)

    monkeypatch.setattr(session.grid, "classify", classify)
    depth = np.full((3, 3), 150, dtype=np.float32)
    session.feed_camera(CameraFrame(4, 1, stamp, 2, depth), now=1.0)
    assert lock_free == [True], "control loop would wait for depth classification"
    assert session._prepared["ground_truth"][0] == (1, stamp)


def test_prepared_and_inline_observations_update_the_map_identically():
    stamp = 1700000000000000000
    depth = np.full((3, 3), 150, dtype=np.float32)
    depth[2, 1] = 90  # a return well below the DEM: a hazard cell
    results = []
    for prepare in (True, False):
        session = _posed_session(stamp)
        if not prepare:
            session._prepare_observation = lambda key, frame: None
        session.feed_camera(CameraFrame(4, 1, stamp, 2, depth), now=1.0)
        session.feed_lidar(LidarScan(0, 1, stamp, np.array([[2.0, 0, 0]]), 1, 1), now=1.0)
        with session.lock:
            session._consume(1.0)
        assert not session._prepared
        health = {k: {kk: vv for kk, vv in v.items() if not kk.endswith("_s")}  # durations differ
                  for k, v in session.health.items()}
        results.append((session.grid.raw_blocked.copy(), session.grid.revision, health))
    np.testing.assert_array_equal(results[0][0], results[1][0])
    assert results[0][1:] == results[1][1:]
    assert results[0][0].any()
