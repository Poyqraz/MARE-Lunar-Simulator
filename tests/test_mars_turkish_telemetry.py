import json
import socket
import time
import urllib.request

import numpy as np
import pytest

from mars_rover.bridge import BridgeServer, JsonObjectStream, TurkishRoverTelemetryStream
from mars_rover.drive import Calibration
from mars_rover.nav_service import NavigationService
from mars_rover.planning import TerrainMap
from test_mars_sensors import lidar_packet, nav_packet


# Exact observed punctuation/field layout; synthetic timestamps preserve privacy.
FRAME = (b'{"time": 0,033, "x" : -12.600,019, "y": 12.603,5, "z": 628,473, '
         b'"roll": 0, "pitch": 0, "yaw": -90, "vx": 0, "vy": 0, "vz": 0, '
         b'"wx": 0, "wy": 0, "wz": 0, "t_ns": "1700000000500000000"}')
FRAME2 = FRAME.replace(b'0,033', b'0,067').replace(b'628,473', b'628,226').replace(
    b'1700000000500000000', b'1700000000533333333'
)


def test_actual_wire_shape_fragmented_concatenated_and_exact_timestamp():
    stream = TurkishRoverTelemetryStream()
    data = FRAME + FRAME2 + FRAME[:38]
    packets = []
    for offset in range(0, len(data), 7):
        packets.extend(stream.feed(data[offset:offset + 7]))
    assert len(packets) == 2
    assert packets[0]["time"] == pytest.approx(0.033)
    assert packets[0]["x"] == pytest.approx(-12600.019)
    assert packets[0]["y"] == pytest.approx(12603.5)
    assert packets[0]["z"] == pytest.approx(628.473)
    assert packets[0]["t_ns"] == "1700000000500000000"
    assert packets[1]["t_ns"] == "1700000000533333333"
    assert packets[1]["z"] == pytest.approx(628.226)


def test_strict_json_default_does_not_accept_the_same_turkish_data():
    with pytest.raises(ValueError, match="Invalid telemetry JSON"):
        JsonObjectStream().feed(FRAME)


@pytest.mark.parametrize("malformed", [
    FRAME.replace(b'-12.600,019', b'-12.60,019'),
    FRAME.replace(b'"yaw": -90', b'"yaw": -90e2'),
    FRAME.replace(b'"yaw": -90', b'"yaw": NaN'),
    FRAME.replace(b'"yaw": -90', b'"yaw": -90, "yaw": -91'),
    FRAME.replace(b'"pitch": 0, ', b''),
    FRAME.replace(b'"yaw": -90', b'"yaw": -90, "extra": 1'),
    FRAME.replace(b'"1700000000500000000"', b'1700000000500000000'),
    FRAME.replace(b'"1700000000500000000"', b'"0"'),
    FRAME.replace(b'"1700000000500000000"', b'"99999999999999999999"'),
    FRAME.replace(b'0,033', b'0,' + b'1' * 40),
    FRAME.replace(b'0,033', b'0,0' + b'\xff'),
])
def test_turkish_mode_rejects_unknown_or_ambiguous_wire_syntax(malformed):
    with pytest.raises((ValueError, UnicodeError)):
        TurkishRoverTelemetryStream().feed(malformed)


def test_grouping_without_any_comma_fraction_is_ambiguous_and_rejected():
    ambiguous = (b'{"time": 0, "x": -12.600, "y": 12.603, "z": 628, "roll": 0, '
                 b'"pitch": 0, "yaw": -90, "vx": 0, "vy": 0, "vz": 0, "wx": 0, '
                 b'"wy": 0, "wz": 0, "t_ns": "1700000000500000000"}')
    with pytest.raises(ValueError, match="ambiguous"):
        TurkishRoverTelemetryStream().feed(ambiguous)


def test_turkish_mode_rejects_oversized_incomplete_frame():
    with pytest.raises(ValueError, match="64 KiB"):
        TurkishRoverTelemetryStream().feed(b'{' + b'a' * 65536)


def test_real_socket_bridge_receives_observed_format_only_when_enabled():
    with BridgeServer(Calibration(), tcp_port=0, http_port=0, telemetry_format="unreal-tr-v1") as bridge:
        with socket.create_connection(("127.0.0.1", bridge.tcp_port), timeout=2) as peer:
            peer.settimeout(2)
            peer.recv(4096)  # initial stopped command
            peer.sendall(FRAME[:33])
            peer.sendall(FRAME[33:])
            end = time.monotonic() + 2
            while time.monotonic() < end:
                state = bridge.status()
                if state["telemetry_unreal"]:
                    break
                time.sleep(.01)
            assert state["connected"] is True
            assert state["telemetry_format"] == "unreal-tr-v1"
            assert state["telemetry_unreal"]["x"] == pytest.approx(-12600.019)
            assert state["telemetry_unreal"]["t_ns"] == "1700000000500000000"
            assert state["telemetry_timing"]["frames_parsed"] == 1
            assert state["telemetry_timing"]["invalid_stamps"] == 0
            assert state["pose_local_m"]["x"] == pytest.approx(126.00019)
            assert all(value == 0 for value in state["wheel_command_m_s"].values())


def test_invalid_turkish_frame_disconnects_and_clears_active_wheel_commands():
    with BridgeServer(Calibration(), tcp_port=0, http_port=0, telemetry_format="unreal-tr-v1") as bridge:
        with socket.create_connection(("127.0.0.1", bridge.tcp_port), timeout=2) as peer:
            peer.settimeout(2)
            peer.recv(4096)
            peer.sendall(FRAME)
            end = time.monotonic() + 2
            while time.monotonic() < end and not bridge.status()["telemetry_unreal"]:
                time.sleep(.01)
            assert bridge.status()["connected"]
            bridge.state.submit_wheels(dict.fromkeys(("FL", "FR", "BL", "BR"), 0.1))
            peer.sendall(FRAME.replace(b'"yaw": -90', b'"yaw": NaN'))
            end = time.monotonic() + 2
            while time.monotonic() < end:
                state = bridge.status()
                if state["last_error"] and not state["connected"]:
                    break
                time.sleep(.01)
            assert "Invalid unreal-tr-v1" in state["last_error"]
            assert state["connected"] is False
            assert all(value == 0 for value in state["wheel_command_m_s"].values())


def test_navigation_service_accepts_explicit_format_and_exposes_live_pose():
    grid = TerrainMap(np.zeros((254, 254)), 1)
    config = {"schema_version": 1, "manifest_sha256": None, "source": "test",
              "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
              "depth": {"camera_id": 4, "hfov_deg": 90, "to_body": np.eye(4).tolist()}}
    with NavigationService(grid, config, tcp_port=0, bridge_http_port=0, http_port=0, lidar_port=0,
                           camera_port=0, telemetry_format="unreal-tr-v1") as service:
        with socket.create_connection(("127.0.0.1", service.bridge.tcp_port), timeout=2) as peer:
            peer.sendall(FRAME)
            url = f"http://127.0.0.1:{service.http.server_port}/mission/snapshot"
            end = time.monotonic() + 2
            while time.monotonic() < end:
                with urllib.request.urlopen(url, timeout=2) as response:
                    snapshot = json.load(response)
                if snapshot["live_pose"]:
                    break
                time.sleep(.02)
            assert snapshot["live_pose"] is not None
            assert snapshot["pose_fresh"] is True
            assert snapshot["telemetry_format"] == "unreal-tr-v1"
            assert snapshot["mission"] is None
            assert all(value == 0 for value in snapshot["wheel_command_m_s"].values())


def test_turkish_telemetry_can_align_synthetic_lidar_and_depth_at_capture_time():
    grid = TerrainMap(np.zeros((254, 254)), 1)
    config = {"schema_version": 1, "manifest_sha256": None, "source": "test",
              "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
              "depth": {"camera_id": 4, "hfov_deg": 90, "to_body": np.eye(4).tolist()}}
    with NavigationService(grid, config, tcp_port=0, bridge_http_port=0, http_port=0, lidar_port=0,
                           camera_port=0, min_points=1, telemetry_format="unreal-tr-v1") as service:
        with (socket.create_connection(("127.0.0.1", service.bridge.tcp_port), timeout=2) as motor,
              socket.create_connection(("127.0.0.1", service.lidar.port), timeout=2) as lidar,
              socket.create_connection(("127.0.0.1", service.camera.port), timeout=2) as camera):
            motor.sendall(FRAME)
            end = time.monotonic() + 2
            while time.monotonic() < end and service.session.pose is None:
                time.sleep(.01)
            assert service.session.pose is not None
            lidar.sendall(lidar_packet([[2, 0, 0]]))
            camera.sendall(nav_packet(np.full((3, 3), 150, dtype="<f4")))
            while time.monotonic() < end:
                snapshot = service.session.mission_snapshot(service.bridge.status())
                if {"lidar", "ground_truth"} <= set(snapshot["sensor_health"]):
                    break
                time.sleep(.01)
            assert snapshot["sensor_health"]["lidar"]["valid_inside_points"] >= 1
            assert snapshot["sensor_health"]["ground_truth"]["valid_inside_points"] >= 1
            assert snapshot["mission"] is None
            assert all(value == 0 for value in snapshot["wheel_command_m_s"].values())
