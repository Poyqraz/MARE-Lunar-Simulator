import importlib
import json
import socket
import time
import urllib.request

import numpy as np

from mars_rover.planning import TerrainMap, PlanningLimits
from test_mars_sensors import lidar_packet, nav_packet


def test_real_packet_sockets_reach_control_and_sensor_disconnect_stops_it():
    Service = importlib.import_module("mars_rover.nav_service").NavigationService
    grid = TerrainMap(np.zeros((20, 20)), 1, PlanningLimits(robot_radius_m=0))
    config = {
        "schema_version": 1,
        "source": "test",
        "manifest_sha256": None,
        "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
        "depth": {
            "camera_id": 4,
            "hfov_deg": 90,
            "to_body": [[0, 0, 1, 0], [-1, 0, 0, 0], [0, -1, 0, 1], [0, 0, 0, 1]],
        },
    }
    with Service(
        grid, config, tcp_port=0, bridge_http_port=0, http_port=0, lidar_port=0, camera_port=0, min_points=1, settle_s=0
    ) as service:
        with (
            socket.create_connection(("127.0.0.1", service.bridge.tcp_port), timeout=2) as motor,
            socket.create_connection(("127.0.0.1", service.lidar.port), timeout=2) as lidar,
            socket.create_connection(("127.0.0.1", service.camera.port), timeout=2) as camera,
        ):
            motor.sendall(
                json.dumps(dict(x=-500, y=500, z=0, roll=0, pitch=0, yaw=180, t_ns="1700000000500000000")).encode()
            )
            url = f"http://127.0.0.1:{service.http.server_port}"
            request = urllib.request.Request(
                url + "/goal", data=b'{"x":10,"y":5}', headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                assert json.load(response)["ok"]
            lidar.sendall(lidar_packet([[2, 0, 0]]))
            depth = np.full((3, 3), np.nan, dtype="<f4")
            depth[2, 1] = 150
            camera.sendall(nav_packet(depth))
            data = b""
            moving = False
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                data += motor.recv(4096)
                while b"\n" in data:
                    raw, data = data.split(b"\n", 1)
                    packet = json.loads(raw)
                    if packet["FL"] < 0 and packet["FR"] < 0:
                        moving = True
                if moving:
                    break
            assert moving
            camera.shutdown(socket.SHUT_RDWR)
            deadline = time.monotonic() + 1
            stopped = False
            while time.monotonic() < deadline:
                data += motor.recv(4096)
                while b"\n" in data:
                    raw, data = data.split(b"\n", 1)
                    packet = json.loads(raw)
                    stopped = all(packet[k] == 0 for k in ("FL", "FR", "BL", "BR"))
                if stopped:
                    break
            assert stopped


def test_mission_map_and_legacy_stop_api_are_connected():
    Service = importlib.import_module("mars_rover.nav_service").NavigationService
    grid = TerrainMap(np.zeros((10, 10)), 1, PlanningLimits(robot_radius_m=0))
    config = {
        "schema_version": 1,
        "manifest_sha256": None,
        "source": "test",
        "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
        "depth": {"camera_id": 4, "hfov_deg": 90, "to_body": np.eye(4).tolist()},
    }
    with Service(grid, config, tcp_port=0, bridge_http_port=0, http_port=0, lidar_port=0, camera_port=0) as service:
        base = f"http://127.0.0.1:{service.http.server_port}"
        with urllib.request.urlopen(base + "/") as response:
            assert "Jezero görev kontrolü" in response.read().decode()
        with urllib.request.urlopen(base + "/map") as response:
            data = json.load(response)
            assert data["extent_m"] == [9, 9] and len(data["blocked"]) == 100
        service.session.set_goal((5, 5))
        request = urllib.request.Request(
            f"http://127.0.0.1:{service.bridge.http_port}/stop",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            assert json.load(response)["ok"]
        assert service.session.status()["goal"] is None
