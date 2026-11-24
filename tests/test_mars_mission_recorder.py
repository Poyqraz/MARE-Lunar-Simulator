"""The optional recorder must preserve evidence without commanding the rover."""

import importlib.util
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest


def recorder():
    path = Path(__file__).parents[1] / "tools" / "record_mars_mission.py"
    spec = importlib.util.spec_from_file_location("record_mars_mission", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Clock:
    def __init__(self):
        self.value = 0.0

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


def test_records_new_mission_and_its_actual_abort_reason(tmp_path):
    m = recorder()
    clock = Clock()
    snapshots = iter([
        {"state": "idle", "mission": None},
        {"state": "following", "mission": {"mission_id": "m1", "closed": False}},
        {"state": "blocked", "mission": {"mission_id": "m1", "closed": True, "error": "blocked cell"}},
    ])
    requests = []

    def get(path):
        requests.append(path)
        if path == "/mission/snapshot":
            return next(snapshots)
        assert path == "/mission/export"
        return {"missions": [{"mission_id": "m1", "status": "blocked", "error": "blocked cell"}]}

    result = m.record(tmp_path, duration_s=10, poll_s=1, checkpoint_s=1,
                      get_json=get, now=clock.now, sleep=clock.sleep, log=lambda _: None)
    assert result["reason"] == "mission_finished"
    assert json.loads(result["mission"].read_text())["missions"][-1]["error"] == "blocked cell"
    samples = json.loads(result["samples"].read_text())
    assert [s["snapshot"]["state"] for s in samples["samples"]] == ["idle", "following", "blocked"]
    assert set(requests) == {"/mission/snapshot", "/mission/export"}


def test_preserves_last_good_checkpoint_when_service_disappears(tmp_path):
    m = recorder()
    clock = Clock()
    snapshots = iter([
        {"state": "idle", "mission": None},
        {"state": "following", "mission": {"mission_id": "m1", "closed": False}},
    ])
    export_count = 0

    def get(path):
        nonlocal export_count
        if path == "/mission/export":
            export_count += 1
            if export_count > 1:
                raise ConnectionRefusedError("service unavailable")
            return {"missions": [{"mission_id": "m1", "status": "following"}]}
        assert path == "/mission/snapshot"
        try:
            return next(snapshots)
        except StopIteration:
            raise ConnectionRefusedError("service unavailable") from None

    result = m.record(tmp_path, duration_s=10, poll_s=1, checkpoint_s=1,
                      get_json=get, now=clock.now, sleep=clock.sleep, log=lambda _: None)
    assert result["reason"] == "service_unavailable"
    assert json.loads(result["mission"].read_text())["missions"][0]["mission_id"] == "m1"
    samples = json.loads(result["samples"].read_text())
    assert any("error" in sample for sample in samples["samples"])


def test_new_empty_service_session_does_not_replace_last_mission_checkpoint(tmp_path):
    m = recorder()
    clock = Clock()
    snapshots = iter([
        {"state": "idle", "mission": None, "session_id": "s1"},
        {"state": "following", "mission": {"mission_id": "m1", "closed": False}, "session_id": "s1"},
        {"state": "disconnected", "mission": None, "session_id": "s2"},
    ])
    seen_session = ["s1"]

    def get(path):
        if path == "/mission/snapshot":
            value = next(snapshots)
            seen_session[0] = value["session_id"]
            return value
        assert path == "/mission/export"
        return {"missions": [{"mission_id": "m1", "status": "following"}] if seen_session[0] == "s1" else []}

    result = m.record(tmp_path, duration_s=10, poll_s=1, checkpoint_s=1,
                      get_json=get, now=clock.now, sleep=clock.sleep, log=lambda _: None)
    assert result["reason"] == "session_changed"
    assert json.loads(result["mission"].read_text())["missions"][0]["mission_id"] == "m1"
    samples = json.loads(result["samples"].read_text())
    assert samples["samples"][-1]["snapshot"]["session_id"] == "s2"


def test_previous_finished_mission_does_not_end_wait_for_next_goal(tmp_path):
    m = recorder()
    clock = Clock()
    old = {"state": "arrived", "mission": {"mission_id": "old", "closed": True}}

    def get(path):
        if path == "/mission/snapshot":
            return old
        assert path == "/mission/export"
        return {"missions": [{"mission_id": "old", "status": "arrived"}]}

    result = m.record(tmp_path, duration_s=3, poll_s=1, checkpoint_s=1,
                      get_json=get, now=clock.now, sleep=clock.sleep, log=lambda _: None)
    assert result["reason"] == "timeout"
    assert json.loads(result["samples"].read_text())["tracked_mission_id"] is None


def test_real_http_recording_only_reads_the_two_mission_endpoints(tmp_path, monkeypatch):
    m = recorder()
    clock = Clock()
    seen = []
    snapshots = iter([
        {"state": "idle", "mission": None},
        {"state": "following", "mission": {"mission_id": "m2", "closed": False}},
        {"state": "arrived", "mission": {"mission_id": "m2", "closed": True}},
    ])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            seen.append((self.command, self.path))
            value = next(snapshots) if self.path == "/mission/snapshot" else {"missions": []}
            payload = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    original = m.urllib.request.urlopen
    base = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(m.urllib.request, "urlopen",
                        lambda url, timeout: original(url.replace("http://127.0.0.1:8766", base), timeout=timeout))
    try:
        result = m.record(tmp_path, duration_s=10, poll_s=1, checkpoint_s=1,
                          get_json=m.read_local_json, now=clock.now, sleep=clock.sleep, log=lambda _: None)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
    assert result["reason"] == "mission_finished"
    assert set(seen) == {("GET", "/mission/snapshot"), ("GET", "/mission/export")}


def fusion_fixture():
    stamp = "1700000000000000000"
    mission = {"mission_id": "m1", "session_id": "s1", "status": "blocked", "error": "no route"}
    frame = {"source": "lidar", "mission_id": "m1", "session_id": "s1", "frame_id": 9,
             "stamp_ns": stamp, "new_cells_total": 3, "new_cells_truncated": 0}
    export = {"missions": [mission], "obstacle_diagnostics": {"enabled": True, "frames_evicted": 0,
                                                              "frames": [frame]}}
    shadow = {"status": "sampled_comparison", "session_id": "s1", "lidar_stamp_ns": stamp,
              "depth_stamp_ns": stamp, "shared_bins": 20, "lidar_hazard_depth_ground_like_bins": 3,
              "lidar_negative_depth_ground_like_bins": 2}
    return export, shadow


def test_shadow_recorder_matches_recorded_timestamp_without_sending_commands(tmp_path):
    m, clock = recorder(), Clock()
    export, shadow = fusion_fixture()
    base = {"session_id": "s1", "pose_fresh": True, "capture_clock_advancing": True,
            "fusion_shadow_enabled": True, "speed_estimate_m_s": 0.001,
            "wheel_command_m_s": {"FL": 0, "FR": 0, "BL": 0, "BR": 0}}
    snapshots = iter([{**base, "state": "idle", "mission": None},
                      {**base, "state": "following", "mission": {"mission_id": "m1", "closed": False}},
                      {**base, "state": "blocked", "mission": {"mission_id": "m1", "closed": True}}])
    requests, lines = [], []

    def get(path):
        requests.append(path)
        if path == "/mission/snapshot":
            return next(snapshots)
        if path == "/mission/export":
            return export
        assert path == "/dashboard/fusion-shadow"
        return shadow

    result = m.record(tmp_path, duration_s=10, poll_s=1, checkpoint_s=1, capture_fusion=True,
                      get_json=get, now=clock.now, sleep=clock.sleep, log=lines.append)
    assert result["reason"] == "mission_finished"
    assert set(requests) == {"/mission/snapshot", "/mission/export", "/dashboard/fusion-shadow"}
    samples = json.loads(result["samples"].read_text())
    assert samples["samples"][1]["fusion_shadow"] == shadow
    summary_line = next(line for line in lines if line.startswith("MARS_FUSION_RUN: "))
    summary = json.loads(summary_line.removeprefix("MARS_FUSION_RUN: "))
    assert summary["matched_change_frames_by_stamp"] == 1
    assert summary["unmatched_change_frames"] == 0
    assert summary["max_lidar_hazard_depth_ground_bins_matched"] == 3
    assert summary["max_lidar_negative_depth_ground_bins_matched"] == 2
    assert summary["retained_map_change_frames_by_source"] == {"lidar": 1, "ground_truth": 0, "stereo": 0}
    assert summary["retained_new_cells_by_source"] == {"lidar": 3, "ground_truth": 0, "stereo": 0}
    assert "not matching rays" in summary["limits"]


@pytest.mark.parametrize("defect,reason", [
    ("shadow_off", "fusion_shadow_disabled"),
    ("moving", "preflight_unsuitable"),
    ("pose_stale", "preflight_unsuitable"),
    ("pose_not_boolean", "preflight_unsuitable"),
    ("clock_stopped", "preflight_unsuitable"),
    ("session_missing", "preflight_unsuitable"),
    ("speed", "preflight_unsuitable"),
    ("wheel", "preflight_unsuitable"),
    ("active_without_id", "preflight_unsuitable"),
    ("diagnostics_off", "obstacle_diagnostics_disabled"),
])
def test_shadow_preflight_never_reports_ready_when_required_state_is_missing(tmp_path, defect, reason):
    m, clock = recorder(), Clock()
    export, _ = fusion_fixture()
    snapshot = {"state": "idle", "mission": None, "session_id": "s1", "pose_fresh": True,
                "capture_clock_advancing": True, "fusion_shadow_enabled": True, "speed_estimate_m_s": 0,
                "wheel_command_m_s": {"FL": 0, "FR": 0, "BL": 0, "BR": 0}}
    if defect == "shadow_off":
        snapshot["fusion_shadow_enabled"] = False
    elif defect == "moving":
        snapshot.update(state="following", mission={"mission_id": "m1", "closed": False})
    elif defect == "pose_stale":
        snapshot["pose_fresh"] = False
    elif defect == "pose_not_boolean":
        snapshot["pose_fresh"] = "true"
    elif defect == "clock_stopped":
        snapshot["capture_clock_advancing"] = False
    elif defect == "session_missing":
        snapshot["session_id"] = None
    elif defect == "speed":
        snapshot["speed_estimate_m_s"] = 0.03
    elif defect == "wheel":
        snapshot["wheel_command_m_s"]["FR"] = 0.1
    elif defect == "active_without_id":
        snapshot["mission"] = {"closed": False}
    else:
        export["obstacle_diagnostics"]["enabled"] = False
    requests, lines = [], []

    def get(path):
        requests.append(path)
        if path == "/mission/snapshot":
            return snapshot
        assert path == "/mission/export"
        return export

    result = m.record(tmp_path, duration_s=10, capture_fusion=True, get_json=get,
                      now=clock.now, sleep=clock.sleep, log=lines.append)
    assert result["reason"] == reason
    assert not any(line.startswith("KAYIT_HAZIR") for line in lines)
    assert "/dashboard/fusion-shadow" not in requests
    assert all(path.startswith("/mission/") for path in requests)


def test_fusion_request_failure_does_not_abort_mission_recording(tmp_path):
    m, clock = recorder(), Clock()
    export, shadow = fusion_fixture()
    base = {"session_id": "s1", "pose_fresh": True, "capture_clock_advancing": True,
            "fusion_shadow_enabled": True, "speed_estimate_m_s": 0,
            "wheel_command_m_s": {"FL": 0, "FR": 0, "BL": 0, "BR": 0}}
    snapshots = iter([{**base, "state": "idle", "mission": None},
                      {**base, "state": "following", "mission": {"mission_id": "m1", "closed": False}},
                      {**base, "state": "arrived", "mission": {"mission_id": "m1", "closed": True}}])
    calls = 0

    def get(path):
        nonlocal calls
        if path == "/mission/snapshot":
            return next(snapshots)
        if path == "/mission/export":
            return export
        assert path == "/dashboard/fusion-shadow"
        calls += 1
        if calls == 2:
            raise TimeoutError("comparison timeout")
        return shadow

    result = m.record(tmp_path, duration_s=10, poll_s=1, capture_fusion=True,
                      get_json=get, now=clock.now, sleep=clock.sleep, log=lambda _: None)
    assert result["reason"] == "mission_finished"
    samples = json.loads(result["samples"].read_text())["samples"]
    assert samples[1]["fusion_shadow_error"] == "comparison timeout"
    assert result["mission"].exists()


def test_summary_rejects_cross_session_invalid_and_ambiguous_stamp_matches():
    m = recorder()
    export, shadow = fusion_fixture()
    snapshot = {"session_id": "s1", "mission": {"mission_id": "m1"}}
    wrong_session = {**shadow, "session_id": "s2"}
    invalid = {**shadow, "depth_stamp_ns": "1700000001000000000"}
    duplicate = dict(export["obstacle_diagnostics"]["frames"][0], frame_id=10)
    export["obstacle_diagnostics"]["frames"].append(duplicate)
    samples = [{"snapshot": snapshot, "fusion_shadow": wrong_session},
               {"snapshot": snapshot, "fusion_shadow": invalid},
               {"snapshot": snapshot, "fusion_shadow": shadow}]
    result = m.summarize_fusion(samples, export, "m1", samples_evicted=2)
    assert result["matched_change_frames_by_stamp"] == 0
    assert result["ambiguous_recorded_change_frames"] == 2
    assert result["session_mismatches"] == result["invalid_comparisons"] == 1
    assert result["samples_evicted"] == 2
    assert result["max_lidar_hazard_depth_ground_bins_matched"] is None


def test_unmatched_change_frame_does_not_imply_zero_sensor_disagreement():
    m = recorder()
    export, shadow = fusion_fixture()
    shadow["lidar_stamp_ns"] = shadow["depth_stamp_ns"] = "1700000000100000000"
    sample = {"snapshot": {"session_id": "s1", "mission": {"mission_id": "m1"}}, "fusion_shadow": shadow}
    result = m.summarize_fusion([sample], export, "m1")
    assert result["unmatched_change_frames"] == 1 and result["matched_change_frames_by_stamp"] == 0
    assert result["max_lidar_hazard_depth_ground_bins_matched"] is None


def test_incomplete_map_diagnostic_never_claims_a_known_change_count():
    m = recorder()
    export, shadow = fusion_fixture()
    frame = export["obstacle_diagnostics"]["frames"][0]
    frame.pop("new_cells_total")
    frame["collection_error"] = "diagnostic unavailable"
    sample = {"snapshot": {"session_id": "s1", "mission": {"mission_id": "m1"}}, "fusion_shadow": shadow}
    result = m.summarize_fusion([sample], export, "m1")
    assert result["matched_change_frames_by_stamp"] == 0
    assert result["retained_new_cells_by_source"]["lidar"] is None
    assert result["retained_map_change_frames_by_source"]["lidar"] is None
    assert result["unverifiable_lidar_frames"] == result["lidar_frame_collection_errors"] == 1


def test_shadow_recording_uses_only_three_local_get_endpoints(tmp_path, monkeypatch):
    m, clock = recorder(), Clock()
    export, shadow = fusion_fixture()
    base = {"session_id": "s1", "pose_fresh": True, "capture_clock_advancing": True,
            "fusion_shadow_enabled": True, "speed_estimate_m_s": 0,
            "wheel_command_m_s": {"FL": 0, "FR": 0, "BL": 0, "BR": 0}}
    snapshots = iter([{**base, "state": "idle", "mission": None},
                      {**base, "state": "following", "mission": {"mission_id": "m1", "closed": False}},
                      {**base, "state": "blocked", "mission": {"mission_id": "m1", "closed": True}}])
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            seen.append((self.command, self.path))
            values = {"/mission/export": export, "/dashboard/fusion-shadow": shadow}
            value = next(snapshots) if self.path == "/mission/snapshot" else values[self.path]
            payload = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    original = m.urllib.request.urlopen
    base_url = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(m.urllib.request, "urlopen",
                        lambda url, timeout: original(url.replace("http://127.0.0.1:8766", base_url), timeout=timeout))
    lines = []
    try:
        result = m.record(tmp_path, duration_s=10, poll_s=1, checkpoint_s=1, capture_fusion=True,
                          get_json=m.read_local_json, now=clock.now, sleep=clock.sleep, log=lines.append)
        with pytest.raises(ValueError):
            m.read_local_json("/goal")
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
    assert result["reason"] == "mission_finished"
    assert set(seen) == {("GET", "/mission/snapshot"), ("GET", "/mission/export"),
                         ("GET", "/dashboard/fusion-shadow")}
    summary = json.loads(next(line for line in lines if line.startswith("MARS_FUSION_RUN: ")).split(": ", 1)[1])
    assert summary["matched_change_frames_by_stamp"] == 1
