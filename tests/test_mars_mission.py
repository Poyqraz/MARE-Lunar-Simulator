import copy
import json
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from mars_rover.navigation import NavigationSession
from mars_rover.planning import PlanningLimits, TerrainMap
from mars_rover.sensors import CameraFrame, LidarScan, pose_from_telemetry

EPOCH = 1700000000000000000


def telemetry(t=0, x=5.0, y=5.0, connection=1):
    return {
        "connected": True,
        "connection_id": connection,
        "telemetry_age_s": 0,
        "telemetry_unreal": dict(
            x=-100 * x, y=100 * y, z=0, roll=0, pitch=0, yaw=180, t_ns=str(EPOCH + round(t * 1e9))
        ),
    }


def session():
    grid = TerrainMap(np.zeros((30, 30)), 1, PlanningLimits(robot_radius_m=0))
    config = {
        "schema_version": 1,
        "manifest_sha256": None,
        "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
        "depth": {
            "camera_id": 4,
            "hfov_deg": 90,
            "to_body": [[0, 0, 1, 0], [-1, 0, 0, 0], [0, -1, 0, 1], [0, 0, 0, 1]],
        },
    }
    return NavigationSession(grid, config, min_points=1, settle_s=0)


def capture(s, *, now=1, stamp=EPOCH):
    s.feed_lidar(LidarScan(0, 1, stamp, np.array([[2.0, 0, 0]]), 1, 1), now=now)
    depth = np.full((3, 3), np.nan, dtype="float32")
    depth[2, 1] = 150
    s.feed_camera(CameraFrame(4, 1, stamp, 2, depth), now=now)


def test_idle_and_terminal_observation_is_live_but_finished_mission_is_frozen():
    s = session()
    s.step(telemetry(), now=1)
    assert s.status()["pose_local_m"][:2] == (5, 5)
    s.set_goal((10, 5))
    s.step(telemetry(0.2, 5.02), now=1.2)
    s.step(telemetry(0.4, 5.04), now=1.4)
    a = s.mission_snapshot(now=1.4)
    assert a["mission"]["travelled_xy_m"] == pytest.approx(0.02)
    s.stop()
    frozen = copy.deepcopy(s.mission.export()["missions"][-1])
    s.step(telemetry(0.6, 5.06), now=1.6)
    b = s.mission_snapshot(now=1.6)
    assert b["live_pose"]["position_m"][0] == pytest.approx(5.06)
    assert s.mission.export()["missions"][-1] == frozen
    assert b["mission"]["status"] == "stopped"
    assert b["mission"]["start_pose"]["position_m"][0] == pytest.approx(5.02)
    assert isinstance(b["live_pose"]["stamp_ns"], str)
    assert b["position_source"] == "simulation telemetry"
    assert b["unavailable"]["battery_percent"] is None


def test_replan_preserves_initial_route_and_start_then_new_play_cancels_goal():
    s = session()
    s.set_goal((12, 5))
    capture(s)
    s.step(telemetry(), now=1)
    first = s.mission_snapshot(now=1)
    assert first["mission"]["plan_revision"] == 1
    s.grid.observe(np.array([[8, 5, 0.5]]))
    assert s.step(telemetry(), now=1.01) == (0, 0)
    s.step(telemetry(), now=1.02)
    after = s.mission_snapshot(now=1.02)
    assert after["mission"]["mission_id"] == first["mission"]["mission_id"]
    assert after["mission"]["initial_plan"] == first["mission"]["initial_plan"]
    assert after["mission"]["plan_revision"] == 2
    assert after["mission"]["active_plan"] != first["mission"]["active_plan"]
    s.step(telemetry(0.2, connection=2), now=1.2)
    reset = s.mission_snapshot(now=1.2)
    assert s.goal is None and reset["session_id"] != first["session_id"]
    assert s.mission.export()["missions"][-1]["status"] == "new_connection"


def test_gaps_and_teleports_are_not_counted_as_driven_distance():
    s = session()
    s.set_goal((20, 5))
    s.step(telemetry(), now=1)
    s.step(telemetry(0.2, 5.02), now=1.2)
    s.step(telemetry(2, 6), now=3)
    a = s.mission_snapshot(now=3)
    assert a["mission"]["travelled_xy_m"] == pytest.approx(0.02)
    assert not a["mission"]["distance_complete"]
    assert s.mission.trail()["points"][-1]["break_before"]
    s.step(telemetry(2.2, 25), now=3.2)
    assert s.goal is None
    assert s.mission.export()["missions"][-1]["status"] == "teleport"


def test_snapshots_are_detached_and_archive_limits_are_explicit():
    from mars_rover.mission import MissionHistory

    m = MissionHistory(None, max_points=3, max_missions=2, max_events=3, max_plans=2)
    for k in range(4):
        m.begin((10, 5))
        for i in range(5):
            p = pose_from_telemetry(telemetry(k * 2 + i * 0.2, 5 + i * 0.01)["telemetry_unreal"])
            m.observe(p)
        m.finish("stopped")
    report = m.export()
    assert len(report["missions"]) == 2 and report["limits"]["missions_evicted"] == 2
    assert len(report["session_trail"]) <= 3 and len(report["events"]) <= 3
    assert m.trail(after_seq=0)["truncated"]
    assert m.trail()["points"][0]["break_before"]
    report["missions"][-1]["goal"] = (-999, 5)
    assert m.export()["missions"][-1]["goal"][0] == 10
    json.dumps(m.export(), allow_nan=False)


def test_arrived_record_is_frozen_while_live_pose_keeps_updating():
    s = session()
    s.set_goal((5.2, 5))
    capture(s)
    s.step(telemetry(), now=1)
    s.step(telemetry(), now=1.01)
    assert s.state == "arrived"
    saved = s.mission.export()["missions"][-1]
    s.step(telemetry(0.2, 5.02), now=1.2)
    assert s.status()["pose_local_m"][0] == pytest.approx(5.02)
    assert s.mission.export()["missions"][-1] == saved
    assert saved["remaining_route_m"] == 0


def test_cancelled_queued_goal_does_not_borrow_a_pose_from_before_its_start():
    s = session()
    s.step(telemetry(), now=1)
    s.set_goal((10, 5))
    s.stop()
    record = s.mission.export()["missions"][-1]
    assert record["start_pose"] is None and record["end_pose"] is None
    assert not record["trail"]


def test_clock_reset_cancels_goal_and_retained_trail_keeps_its_original_session():
    s = session()
    s.set_goal((10, 5))
    s.step(telemetry(1), now=1)
    first = s.mission_snapshot(now=1)
    s.step(telemetry(0), now=1.1)
    assert s.goal is None
    assert s.mission_snapshot(now=1.1)["session_id"] != first["session_id"]
    old = s.mission.trail(mission_id=first["mission"]["mission_id"])
    assert old["session_id"] == first["session_id"]
    assert not s.mission.export()["missions"][-1]["distance_complete"]


def test_exact_eviction_cursor_does_not_report_missing_future_points():
    from mars_rover.mission import MissionHistory

    m = MissionHistory(None, max_points=2)
    for i in range(4):
        m.observe(pose_from_telemetry(telemetry(i * 0.2, 5 + i * 0.01)["telemetry_unreal"]))
    assert m.trail(after_seq=0)["truncated"]
    assert not m.trail(after_seq=2)["truncated"]
    assert m.export()["session_trail"][0]["break_before"]


def test_repeated_paused_pose_and_stale_pose_are_not_new_speed_measurements():
    s = session()
    s.step(telemetry(), now=1)
    s.step(telemetry(0.2, 5.02), now=1.2)
    assert s.mission_snapshot(now=1.2)["speed_estimate_m_s"] == pytest.approx(0.1)
    s.step(telemetry(0.2, 5.02), now=2)
    paused = s.mission_snapshot(now=2)
    assert not paused["capture_clock_advancing"] and paused["speed_estimate_m_s"] is None
    assert not s.mission_snapshot(now=3)["pose_fresh"]


def test_slow_map_reply_does_not_hold_control_lock_and_mission_api_is_read_only(monkeypatch):
    from mars_rover.nav_service import NavigationService

    s = session()
    with NavigationService(
        s.grid, s.config, tcp_port=0, bridge_http_port=0, http_port=0, camera_port=0, lidar_port=0
    ) as service:
        base = f"http://127.0.0.1:{service.http.server_port}"
        entered, release = threading.Event(), threading.Event()
        handler = service.http.RequestHandlerClass
        original = handler.reply

        def delayed(self, code, value):
            if isinstance(value, dict) and "blocked" in value:
                entered.set()
                assert release.wait(2)
            return original(self, code, value)

        monkeypatch.setattr(handler, "reply", delayed)

        def get_map():
            with urllib.request.urlopen(base + "/map", timeout=3) as r:
                return json.load(r)

        with ThreadPoolExecutor(1) as pool:
            f = pool.submit(get_map)
            try:
                assert entered.wait(1)
                acquired = service.session.lock.acquire(timeout=0.2)
                if acquired:
                    service.session.lock.release()
                assert acquired, "Network reply still holds the motor-control lock"
            finally:
                release.set()
            assert f.result()["width"] == 30
        service.session.set_goal((10, 5))
        mid = service.session.mission_snapshot()["mission"]["mission_id"]
        for path in [
            "/mission/snapshot",
            "/mission/trail?after_seq=0",
            "/mission/events?after_seq=0",
            "/mission/export",
        ]:
            with urllib.request.urlopen(base + path, timeout=2) as response:
                json.load(response)
        assert service.session.goal == (10, 5)
        assert service.session.mission_snapshot()["mission"]["mission_id"] == mid
