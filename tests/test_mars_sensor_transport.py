import json
import socket
import struct
import time
import urllib.request

import numpy as np

from mars_rover.nav_service import NavigationService
from mars_rover.planning import PlanningLimits, TerrainMap
from mars_rover.sensors import LidarScan


def service():
    config = {"schema_version": 1, "manifest_sha256": None,
              "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
              "depth": {"camera_id": 4, "hfov_deg": 90, "to_body": np.eye(4).tolist()}}
    return NavigationService(TerrainMap(np.zeros((10, 10)), 1, PlanningLimits(robot_radius_m=0)),
                             config, tcp_port=0, bridge_http_port=0, http_port=0,
                             lidar_port=0, camera_port=0, obstacle_diagnostics=True,
                             lidar_pose_source="cpu_capture")


def lidar_packet(version):
    header = struct.pack("<4sBBHQdffIIII", b"LIDR", version, 0, 3 if version == 2 else 1,
                         version, 1700000000.0, 90, 30, 1, 1, 1, 20)
    pose = struct.pack("<12d", *np.eye(4)[:3].ravel()) if version == 2 else b""
    return header + pose + struct.pack("<ffffHH", 1, 0, 0, 20, 0, 0)


def test_rejected_lidar_connection_keeps_the_cause_and_discards_pending_frame():
    with service() as nav:
        # An accepted CPU packet followed by a legacy packet reproduces a
        # producer/consumer mismatch over the real TCP listener.
        with socket.create_connection(("127.0.0.1", nav.lidar.port), timeout=2) as peer:
            peer.sendall(lidar_packet(2) + lidar_packet(1))
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                report = nav.sensor_transport_diagnostics()["lidar"]
                if report["events"]:
                    break
                time.sleep(0.01)
            else:
                raise AssertionError("LiDAR listener did not report the rejected packet")
        assert report["events"] == 1
        assert report["last_event"] == "LiDAR packet pose source does not match the configured pose source"
        assert report["last_detailed_error"] == report["last_event"]
        assert report["last_detailed_error_event"] == 1
        assert report["active_connections"] == 0
        assert "lidar" not in nav.session.latest
        assert "lidar" not in nav.session.health
        assert nav.feeds.scan is None
        base = f"http://127.0.0.1:{nav.http.server_port}"
        for endpoint in ("/status", "/mission/snapshot"):
            with urllib.request.urlopen(base + endpoint, timeout=3) as response:
                result = json.load(response)
            assert result["lidar_pose_source"] == "cpu_capture"
            assert result["sensor_transport"]["lidar"] == report


def test_closed_transport_invalidates_pending_only_for_its_sensor():
    nav = service()
    stamp = 1700000000000000000
    scan = LidarScan(0, 1, stamp, np.zeros((1, 3)), 1, 1, np.eye(4))
    try:
        nav.session.feed_lidar(scan, now=1)
        nav.session.latest["ground_truth"] = (object(), 1)
        nav.session.health["lidar"] = {"valid_inside_points": 1}
        nav.session.used["lidar"] = (1, stamp)
        nav._sensor_error("lidar", "Sensor connection closed")
        assert "lidar" not in nav.session.latest
        assert "lidar" not in nav.session.health
        assert "lidar" not in nav.session.used
        assert "ground_truth" in nav.session.latest
        nav.session.latest.update({key: (object(), 1) for key in ("left", "right", "stereo")})
        nav.session.used["stereo_pair"] = (1, stamp)
        nav._sensor_error("ground_truth", "camera problem")
        assert not any(key in nav.session.latest for key in ("ground_truth", "left", "right", "stereo"))
        assert "stereo_pair" not in nav.session.used
        assert nav.sensor_transport_diagnostics()["lidar"]["last_event"] == "Sensor connection closed"
        assert nav.sensor_transport_diagnostics()["camera"]["last_detailed_error"] == "camera problem"
    finally:
        nav.close()
