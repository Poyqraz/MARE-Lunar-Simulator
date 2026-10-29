import json
import socket
import time
import urllib.error
import urllib.request

import pytest

from mars_rover.bridge import BridgeServer, JsonObjectStream
from mars_rover.drive import Calibration


def test_unreal_telemetry_has_no_line_separator_and_may_be_split():
    stream = JsonObjectStream()
    assert stream.feed(b'{"x":12') == []
    assert stream.feed(b',"y":3}\x00{"x":4}') == [{"x": 12, "y": 3}, {"x": 4}]
    with pytest.raises(ValueError):
        stream.feed(b'x' * 65537)


def test_complete_malformed_telemetry_is_rejected_without_waiting_for_64k():
    # This is the JSON-like *Blueprint log* format observed in the native
    # session; it is not represented here as captured TCP evidence.
    stream = JsonObjectStream()
    assert stream.feed(b'{"time": 0,033, "x": -12.600,019') == []
    with pytest.raises(ValueError, match="Invalid telemetry JSON"):
        stream.feed(b'}')


def test_braces_and_escapes_inside_fragmented_json_strings_are_not_boundaries():
    payload = json.dumps({"x": 2, "message": 'x } \\ " { y', "nested": {"ok": True}}, ensure_ascii=False).encode()
    stream = JsonObjectStream()
    result = []
    for byte in payload:
        result += stream.feed(bytes([byte]))
    assert result == [{"x": 2, "message": 'x } \\ " { y', "nested": {"ok": True}}]


def test_malformed_rover_telemetry_stops_connection_with_specific_error():
    with BridgeServer(Calibration(), tcp_port=0, http_port=0) as bridge:
        with socket.create_connection(("127.0.0.1", bridge.tcp_port), timeout=2) as peer:
            read_packet(peer, b'')
            peer.sendall(b'{"time": 0,033, "x": -12.600,019}')
            end = time.monotonic() + 2
            while time.monotonic() < end:
                state = bridge.status()
                if state["last_error"] and not state["connected"]:
                    break
                time.sleep(.01)
            assert state["last_error"].startswith("Invalid telemetry JSON")
            assert state["connected"] is False
            assert all(value == 0 for value in state["wheel_command_m_s"].values())


def read_packet(peer, buffer):
    deadline = time.monotonic() + 2
    while b'\n' not in buffer:
        if time.monotonic() > deadline:
            raise AssertionError("bridge did not send a command")
        buffer += peer.recv(4096)
    line, buffer = buffer.split(b'\n', 1)
    return json.loads(line), buffer


def test_http_to_real_tcp_socket_watchdog_telemetry_and_stop():
    with BridgeServer(Calibration(), tcp_port=0, http_port=0, timeout_s=0.15) as bridge:
        base = f"http://127.0.0.1:{bridge.http_port}"
        def post(path, payload):
            request = urllib.request.Request(base + path, data=json.dumps(payload).encode(),
                                             headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=2) as r:
                return json.load(r)
        with pytest.raises(urllib.error.HTTPError) as err:
            post("/wheels", {"FL": 0.1, "FR": 0.2, "BL": 0.3, "BR": 0.4})
        assert err.value.code == 409
        with socket.create_connection(("127.0.0.1", bridge.tcp_port), timeout=2) as peer:
            buffer = b''
            packet, buffer = read_packet(peer, buffer)
            assert packet["FL"] == 0  # every Play begins stopped
            peer.sendall(b'{"x":-100,"y":200,"z":3}{"x":-150,"y":200,"z":4}')
            post("/wheels", {"FL": 0.1, "FR": 0.2, "BL": 0.3, "BR": 0.4})
            for _ in range(10):
                packet, buffer = read_packet(peer, buffer)
                if packet["FL"] != 0:
                    break
            assert packet["FL"] == pytest.approx(-0.182)
            assert packet["BR"] == pytest.approx(-0.728)
            for _ in range(20):
                packet, buffer = read_packet(peer, buffer)
                if packet["FL"] == 0:
                    break
            assert packet["FL"] == packet["BR"] == 0
            with urllib.request.urlopen(base + "/status", timeout=2) as r:
                status = json.load(r)
            assert status["telemetry_unreal"]["x"] == -150
            assert post("/stop", {})["ok"] is True


def test_bridge_counts_capture_gaps_and_resets_statistics_on_new_connection():
    with BridgeServer(Calibration(), tcp_port=0, http_port=0) as bridge:
        start = 1700000000000000000
        with socket.create_connection(("127.0.0.1", bridge.tcp_port), timeout=2) as peer:
            read_packet(peer, b"")
            timestamps = [str(start), str(start + 100_000_000), str(start + 500_000_000),
                          str(start + 500_000_000), str(start + 300_000_000), "bad"]
            peer.sendall(b"".join(json.dumps({"t_ns": value}).encode() for value in timestamps))
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                stats = bridge.status().get("telemetry_timing", {})
                if stats.get("frames_parsed") == len(timestamps):
                    break
                time.sleep(0.01)
            assert stats["frames_parsed"] == 6
            assert stats["capture_gaps_over_250ms"] == 1
            assert stats["max_capture_gap_s"] == pytest.approx(0.4)
            assert stats["duplicate_stamps"] == 1
            assert stats["backward_stamps"] == 1
            assert stats["invalid_stamps"] == 1
            assert all(v == 0 for v in bridge.status()["wheel_command_m_s"].values())
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and bridge.status()["connected"]:
            time.sleep(0.01)
        with socket.create_connection(("127.0.0.1", bridge.tcp_port), timeout=2) as peer:
            read_packet(peer, b"")
            peer.sendall(json.dumps({"t_ns": str(start)}).encode())
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                state = bridge.status()
                if state["connection_id"] == 2 and state.get("telemetry_timing", {}).get("frames_parsed") == 1:
                    break
                time.sleep(0.01)
            assert state["connection_id"] == 2
            assert state["telemetry_timing"]["frames_parsed"] == 1
            assert state["telemetry_timing"]["capture_gaps_over_250ms"] == 0
