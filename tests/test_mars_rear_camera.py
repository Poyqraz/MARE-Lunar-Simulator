import io
import json
import shutil
import socket
import struct
import subprocess
from pathlib import Path
from types import SimpleNamespace
import time
import urllib.error
import urllib.request

import numpy as np
from PIL import Image
import pytest

from mars_rover import nav_service
from mars_rover.dashboard_bridge import LiveFeeds
from mars_rover.planning import PlanningLimits, TerrainMap
from mars_rover.sensors import CameraFrame


def config():
    return {"schema_version": 1, "manifest_sha256": None,
            "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
            "depth": {"camera_id": 4, "to_body": np.eye(4).tolist(), "hfov_deg": 90},
            "stereo": {"left_id": 1, "right_id": 2}}


def test_rear_rgb_is_opt_in_timestamped_and_expires():
    now = [10.0]
    pixels = np.full((8, 8, 4), [0, 0, 255, 255], dtype=np.uint8)
    frame = CameraFrame(10, 42, 1700000000000000000, 1, pixels)
    default = LiveFeeds(config(), clock=lambda: now[0])
    default.camera(frame)
    assert default.frame("cam_rear") is None

    feeds = LiveFeeds(config(), rear_camera_id=10, clock=lambda: now[0])
    feeds.camera(CameraFrame(10, 40, None, 1, pixels))
    assert feeds.frame("cam_rear") is None
    feeds.camera(CameraFrame(11, 41, frame.stamp_ns, 1, pixels))
    assert feeds.frame("cam_rear") is None
    feeds.camera(frame)
    image, stamp = feeds.image("cam_rear", with_stamp=True)
    assert stamp == str(frame.stamp_ns)
    assert Image.open(io.BytesIO(image)).convert("RGB").getpixel((3, 3))[0] > 200
    assert feeds.status()["feeds"]["cam_rear"]["source"] == "unreal_rgb"
    now[0] += 2
    assert feeds.frame("cam_rear") is None
    assert "cam_rear" not in feeds.status()["feeds"]


@pytest.mark.parametrize("camera_id", [0, 1, 2, 4, -1, 256, True, 3.5])
def test_rear_id_must_not_alias_other_cameras(camera_id):
    with pytest.raises(ValueError):
        LiveFeeds(config(), rear_camera_id=camera_id)


def test_rear_camera_endpoint_only_serves_actual_rgb_frames():
    grid = TerrainMap(np.zeros((10, 10)), 1, PlanningLimits(robot_radius_m=0))
    with nav_service.NavigationService(grid, config(), tcp_port=0, bridge_http_port=0,
                                       http_port=0, lidar_port=0, camera_port=0,
                                       rear_camera_id=10) as service:
        url = f"http://127.0.0.1:{service.http.server_port}/dashboard/camera/cam_rear.jpg"
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(url)
        assert error.value.code == 404
        stamp = 1700000000000000000
        pixels = np.full((8, 8, 4), [0, 0, 255, 255], dtype=np.uint8)
        header = struct.pack("<4sBBBBHHQI", b"NAVF", 2, 10, 1, 0, 8, 8, 1, pixels.nbytes)
        packet = header + struct.pack("<Q", stamp) + pixels.tobytes()
        front = struct.pack("<4sBBBBHHQI", b"NAVF", 2, 0, 1, 0, 8, 8, 2, pixels.nbytes)
        front += struct.pack("<Q", stamp) + np.full((8, 8, 4), [255, 0, 0, 255], dtype=np.uint8).tobytes()
        with (socket.create_connection(("127.0.0.1", service.camera.port), timeout=2) as sender,
              socket.create_connection(("127.0.0.1", service.camera.port), timeout=2) as front_sender):
            sender.sendall(packet[:11])
            sender.sendall(packet[11:])
            front_sender.sendall(front)
            deadline = time.monotonic() + 2
            while (service.feeds.frame("cam_rear") is None or service.feeds.frame("cam_central") is None) \
                    and time.monotonic() < deadline:
                time.sleep(0.01)
            with urllib.request.urlopen(url) as response:
                assert response.headers["X-Capture-Stamp-Ns"] == str(stamp)
                assert Image.open(io.BytesIO(response.read())).convert("RGB").getpixel((3, 3))[0] > 200
            front_url = f"http://127.0.0.1:{service.http.server_port}/dashboard/camera/cam_central.jpg"
            with urllib.request.urlopen(front_url) as response:
                assert Image.open(io.BytesIO(response.read())).convert("RGB").getpixel((3, 3))[2] > 200
            service.feeds.clear_camera()
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(url)
            assert error.value.code == 404


def test_cli_passes_explicit_rear_id_to_service(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({}), encoding="utf-8")
    seen = {}

    class FakeService:
        def __init__(self, grid, sensors, **kwargs):
            seen.update(kwargs)
            self.ending = SimpleNamespace(wait=lambda timeout: True)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(nav_service.TerrainMap, "from_bundle", lambda path: object())
    monkeypatch.setattr(nav_service, "NavigationService", FakeService)
    nav_service.main(["--sensors", str(path), "--rear-camera-id", "10"])
    assert seen["rear_camera_id"] == 10


@pytest.mark.parametrize("camera_id", ["-1", "256"])
def test_cli_rejects_out_of_range_rear_id_before_opening_sensors(camera_id):
    with pytest.raises(SystemExit) as error:
        nav_service.main(["--sensors", "not-opened.json", "--rear-camera-id", camera_id])
    assert error.value.code == 2


def test_frontend_fetches_actual_rear_frames_and_reports_loss():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed for the JavaScript adapter behavior test")
    script = Path(__file__).parent / "js" / "dashboard_adapter_rear.js"
    subprocess.run([node, str(script)], check=True, capture_output=True, text=True, timeout=10)
