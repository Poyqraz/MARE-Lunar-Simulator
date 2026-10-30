import io
import json
import threading
import urllib.error
import urllib.request

import numpy as np
import pytest
from PIL import Image

from mars_rover.sensors import CameraFrame, LidarScan


def config():
    return {"lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
            "depth": {"camera_id": 4, "to_body": np.eye(4).tolist(), "hfov_deg": 90},
            "stereo": {"left_id": 1, "right_id": 2}}


def test_real_colour_and_ground_truth_depth_are_labelled_and_expire():
    from mars_rover.dashboard_bridge import LiveFeeds

    clock = [10.0]
    feeds = LiveFeeds(config(), clock=lambda: clock[0])
    bgra = np.full((8, 8, 4), [0, 0, 255, 255], dtype=np.uint8)
    feeds.camera(CameraFrame(0, 1, 100, 1, bgra))
    red, green, blue = Image.open(io.BytesIO(feeds.image("cam_central"))).convert("RGB").getpixel((3, 3))
    assert red > 200 and green < 30 and blue < 30
    assert feeds.status()["center_id_source"] == "assumed_plugin_default"
    depth = np.full((8, 8), 200.0, dtype=np.float32)
    depth[:, :4] = np.nan
    feeds.camera(CameraFrame(4, 1, 100, 2, depth))
    image = Image.open(io.BytesIO(feeds.image("depth_gt"))).convert("RGB")
    assert max(image.getpixel((1, 4))) < 30 and max(image.getpixel((6, 4))) > 100
    assert feeds.status()["feeds"]["depth_gt"]["source"] == "unreal_ground_truth_depth"
    assert feeds.image("depth") is None
    clock[0] += 3
    assert feeds.image("cam_central") is None
    feeds.clear_camera()
    assert feeds.frame("cam_central", 100) is None


def test_display_has_bounded_history_and_exact_image_stamp():
    from mars_rover.dashboard_bridge import LiveFeeds

    feeds = LiveFeeds(config(), clock=lambda: 1.0)
    bgra = np.zeros((8, 8, 4), dtype=np.uint8)
    for stamp in (100, 200, 300):
        feeds.camera(CameraFrame(0, stamp, stamp, 1, bgra))
    assert feeds.frame("cam_central", 100).stamp_ns == 100
    _image, stamp = feeds.image("cam_central", with_stamp=True)
    assert stamp == "300"
    feeds.camera(CameraFrame(0, 4, 400, 1, bgra))
    assert feeds.frame("cam_central", 100) is None
    assert feeds.frame("cam_central", 200).stamp_ns == 200


def test_measured_center_id_selects_only_its_rgb_feed():
    from mars_rover.dashboard_bridge import LiveFeeds

    cfg = config()
    cfg["depth"]["color_camera_id"] = 7
    feeds = LiveFeeds(cfg, clock=lambda: 1.0)
    pixels = np.zeros((8, 8, 4), dtype=np.uint8)
    feeds.camera(CameraFrame(0, 1, 100, 1, pixels))
    assert feeds.frame("cam_central") is None
    feeds.camera(CameraFrame(7, 1, 101, 1, pixels))
    assert feeds.frame("cam_central").camera_id == 7
    assert feeds.status()["center_id_source"] == "measured"


def test_lidar_applies_measured_mount_and_filters_invalid_points():
    from mars_rover.dashboard_bridge import LiveFeeds

    cfg = config()
    transform = np.eye(4)
    transform[:3, 3] = [1.0, 2.0, 3.0]
    cfg["lidar"]["to_body"] = transform.tolist()
    feeds = LiveFeeds(cfg, clock=lambda: 1.0)
    feeds.lidar(LidarScan(0, 2, 123, np.array([[2., 0., 0.], [np.nan, 1., 1.]]), 1, 2))
    scan = feeds.lidar_view()
    assert scan["frame"] == "rover" and scan["count"] == 1
    assert scan["points"] == pytest.approx([3., 2., 3.])
    feeds.clear_lidar()
    assert feeds.lidar_view() is None


def test_disconnect_while_encoding_never_returns_an_old_frame(monkeypatch):
    from mars_rover.dashboard_bridge import LiveFeeds

    feeds = LiveFeeds(config(), clock=lambda: 1.0)
    feeds.camera(CameraFrame(0, 1, 100, 1, np.zeros((8, 8, 4), dtype=np.uint8)))
    started, release = threading.Event(), threading.Event()
    original = Image.Image.save

    def delayed(self, *args, **kwargs):
        started.set()
        assert release.wait(3)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", delayed)
    result = []
    worker = threading.Thread(target=lambda: result.append(feeds.image("cam_central")))
    worker.start()
    assert started.wait(3)
    feeds.clear_camera()
    release.set()
    worker.join(3)
    assert result == [None]


def test_route_projection_and_local_depth_use_measured_transforms():
    from mars_rover.dashboard_bridge import local_depth_view, project_route
    from mars_rover.planning import PlanningLimits, TerrainMap

    grid = TerrainMap(np.zeros((20, 20)), 1, PlanningLimits(robot_radius_m=0))
    body = np.eye(4)
    body[:3, 3] = [5, 5, 0]
    optical = np.array([[0, 0, 1, 0], [-1, 0, 0, 0], [0, -1, 0, 1], [0, 0, 0, 1]], float)
    projected = project_route(grid, body, optical, 90, 640, 480, [(5, 5), (9, 5)])
    assert projected["center"][-1] == pytest.approx([0.5, 2 / 3])
    assert projected["left"][-1][0] < 0.5 < projected["right"][-1][0]
    assert projected["goal"]["dist"] == pytest.approx(4)
    assert projected["center"][0] is None
    behind = project_route(grid, body, optical, 90, 640, 480, [(5, 5), (3, 5)])
    assert all(v is None for v in behind["center"])
    with pytest.raises(ValueError):
        project_route(grid, body, optical, 90, 640, 480, [(5, 5), (22, 5)])
    depth = np.full((5, 5), np.nan)
    depth[2, 2] = 2.0
    view = local_depth_view(grid, body, optical, 90, depth, stride=1)
    assert view["display_only"] and view["source"] == "unreal_ground_truth_depth"
    assert view["z"].count(None) == view["w"] * view["h"] - 1
    assert view["z"][8 * view["w"] + (view["w"] - 1) // 2] == 100


def test_dashboard_endpoints_are_local_and_use_timestamped_observations():
    from mars_rover.nav_service import NavigationService
    from mars_rover.navigation import RouteFollower
    from mars_rover.planning import PlanningLimits, TerrainMap
    from mars_rover.sensors import pose_from_telemetry

    cfg = {"schema_version": 1, "manifest_sha256": None, **config()}
    cfg["depth"]["to_body"] = [[0, 0, 1, 0], [-1, 0, 0, 0], [0, -1, 0, 1], [0, 0, 0, 1]]
    grid = TerrainMap(np.zeros((10, 10)), 1, PlanningLimits(robot_radius_m=0))
    stamp = 1700000000000000000
    with NavigationService(grid, cfg, tcp_port=0, bridge_http_port=0, http_port=0, lidar_port=0, camera_port=0) as s:
        base = f"http://127.0.0.1:{s.http.server_port}"
        with urllib.request.urlopen(base + "/dashboard") as response:
            html = response.read().decode()
            assert "mapCanvas" in html and "mars-adapter.js" in html
        with urllib.request.urlopen(base + "/dashboard/map") as response:
            data = json.load(response)
            assert (data["width"], data["height"], data["resolution"]) == (10, 10, 1)
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/dashboard-assets/../navigation.py")
        s.feeds.camera(CameraFrame(0, 1, stamp, 1, np.full((480, 640, 4), [0, 0, 255, 255], dtype=np.uint8)))
        with urllib.request.urlopen(base + "/dashboard/camera/cam_central.jpg") as response:
            assert response.headers["X-Capture-Stamp-Ns"] == str(stamp)
            assert Image.open(io.BytesIO(response.read())).getpixel((3, 3))[0] > 200
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/dashboard/path-overlay")
        pose = pose_from_telemetry(dict(x=-500, y=500, z=0, roll=0, pitch=0, yaw=180, t_ns=str(stamp)))
        with s.session.lock:
            s.session.pose = pose
            s.session.history.add(pose)
            s.session.follower = RouteFollower([(5, 5), (9, 5)])
        with urllib.request.urlopen(base + f"/dashboard/path-overlay?stamp={stamp}") as response:
            assert json.load(response)["center"][-1] == pytest.approx([0.5, 2 / 3])
        s.feeds.camera(CameraFrame(4, 1, stamp, 2, np.full((48, 64), 200, dtype=np.float32)))
        with urllib.request.urlopen(base + f"/dashboard/local-dem?stamp={stamp}") as response:
            view = json.load(response)
            assert view["stamp_ns"] == str(stamp) and view["display_only"] and view["observed"] > 0
        s.feeds.camera(CameraFrame(0, 2, stamp + 1_000_000_000, 1, np.zeros((480, 640, 4), dtype=np.uint8)))
        with urllib.request.urlopen(base + f"/dashboard/path-overlay?stamp={stamp}") as response:
            assert json.load(response)["stamp_ns"] == str(stamp)
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/dashboard/path-overlay")


def test_editor_viewport_link_does_not_control_the_vehicle():
    from mars_rover.nav_service import NavigationService
    from mars_rover.planning import PlanningLimits, TerrainMap

    cfg = {"schema_version": 1, "manifest_sha256": None, **config()}
    grid = TerrainMap(np.zeros((10, 10)), 1, PlanningLimits(robot_radius_m=0))
    with NavigationService(grid, cfg, tcp_port=0, bridge_http_port=0, http_port=0, lidar_port=0, camera_port=0) as s:
        base = f"http://127.0.0.1:{s.http.server_port}"
        with urllib.request.urlopen(base + "/viewport_camera?applied=idle&rover=none") as response:
            assert json.load(response)["mode"] == "follow"
        request = urllib.request.Request(base + "/dashboard/viewport", data=b'{"mode":"top"}',
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request) as response:
            assert json.load(response)["mode"] == "top"
        with urllib.request.urlopen(base + "/viewport_camera?applied=top&rover=Leo_Raph_C") as response:
            assert json.load(response)["mode"] == "top"
        with urllib.request.urlopen(base + "/dashboard/viewport") as response:
            state = json.load(response)
            assert state["linked"] and state["applied"] == "top" and state["rover"] == "Leo_Raph_C"
        request = urllib.request.Request(base + "/dashboard/viewport", data=b'{"mode":"invalid"}',
                                         headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code == 400 and s.session.goal is None


def test_derived_view_is_discarded_if_camera_disconnects_during_processing(monkeypatch):
    import mars_rover.nav_service as service_module
    from mars_rover.planning import PlanningLimits, TerrainMap
    from mars_rover.sensors import pose_from_telemetry

    cfg = {"schema_version": 1, "manifest_sha256": None, **config()}
    grid = TerrainMap(np.zeros((10, 10)), 1, PlanningLimits(robot_radius_m=0))
    stamp = 1700000000000000000
    with service_module.NavigationService(grid, cfg, tcp_port=0, bridge_http_port=0,
                                          http_port=0, lidar_port=0, camera_port=0) as s:
        pose = pose_from_telemetry(dict(x=-500, y=500, z=0, roll=0, pitch=0, yaw=180, t_ns=str(stamp)))
        with s.session.lock:
            s.session.history.add(pose)
        s.feeds.camera(CameraFrame(4, 1, stamp, 2, np.full((48, 64), 200, dtype=np.float32)))

        def disconnect_during_view(*args, **kwargs):
            s.feeds.clear_camera()
            return {"display_only": True}

        monkeypatch.setattr(service_module, "local_depth_view", disconnect_during_view)
        url = f"http://127.0.0.1:{s.http.server_port}/dashboard/local-dem?stamp={stamp}"
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(url)
        assert error.value.code == 404
