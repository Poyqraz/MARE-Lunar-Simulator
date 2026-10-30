"""The optional recorder must preserve evidence without commanding the rover."""

import importlib.util
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading


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
