import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest


def setup():
    path = Path(__file__).parents[1] / "Content/Python/mars_sensor_setup.py"
    spec = importlib.util.spec_from_file_location("sensor_setup_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def vec(x, y, z):
    return SimpleNamespace(x=x, y=y, z=z)


def component(x=0, y=0, z=0):
    # Unreal yaw 180: native forward -X maps to local east +X.
    return SimpleNamespace(
        get_forward_vector=lambda: vec(-1, 0, 0),
        get_up_vector=lambda: vec(0, 0, 1),
        get_world_location=lambda: vec(x, y, z),
    )


def test_exported_lidar_and_optical_frames_share_one_correct_body_basis():
    m = setup()
    body = m.map_frame(component(-100, 200, 0))
    camera = m.map_frame(component(-120, 200, 50), optical=True)
    relative = np.asarray(m.relative_frame(body, camera))
    np.testing.assert_allclose(relative[:3, 3], [0.2, 0, 0.5], atol=1e-10)
    np.testing.assert_allclose(relative[:3, 0], [0, -1, 0], atol=1e-10)
    np.testing.assert_allclose(relative[:3, 1], [0, 0, -1], atol=1e-10)
    np.testing.assert_allclose(relative[:3, 2], [1, 0, 0], atol=1e-10)
    assert np.linalg.det(relative[:3, :3]) == pytest.approx(1)


def test_parallel_baseline_validation_rejects_a_tilted_or_vertical_pair():
    m = setup()
    left = np.eye(4)
    right = np.eye(4)
    right[0, 3] = 0.2
    assert m.parallel_baseline(left.tolist(), right.tolist()) == pytest.approx(0.2)
    right[1, 3] = 0.1
    with pytest.raises(ValueError):
        m.parallel_baseline(left.tolist(), right.tolist())


def test_nearly_unit_but_nonorthogonal_sensor_axes_fail_before_export():
    m = setup()
    sensor = component()
    # Both vectors have length one, but their dot product is 0.001.
    sensor.get_up_vector = lambda: vec(0.001, 0, (1 - 0.001 ** 2) ** 0.5)
    with pytest.raises(ValueError, match="orthonormal"):
        m.map_frame(sensor)


def test_invalid_sensor_axes_report_component_and_actual_vectors():
    m = setup()
    sensor = component()
    sensor.get_name = lambda: "ObservedLidar"
    sensor.get_forward_vector = lambda: vec(0, 0, 0)
    with pytest.raises(ValueError, match="ObservedLidar") as error:
        m.map_frame(sensor)
    assert "forward=" in str(error.value) and "up=" in str(error.value)


def test_nonfinite_sensor_position_is_rejected():
    m = setup()
    sensor = component(float("nan"), 0, 0)
    with pytest.raises(ValueError, match="finite"):
        m.map_frame(sensor)


def fake_rover_for_sensor_export(*, invalid_lidar=False):
    """Construct an explicit stereo rig and optional invalid LiDAR mount."""
    perspective = object()
    engine = SimpleNamespace(
        EditorLevelLibrary=SimpleNamespace(get_pie_worlds=lambda _: []),
        SceneComponent=object(), UnrealLidarCam=object(), UnrealStereoCam=object(),
        CameraProjectionMode=SimpleNamespace(PERSPECTIVE=perspective),
    )

    def scene(name, position, properties=None, forward=(-1, 0, 0)):
        obj = MagicMock()
        obj.get_name.return_value = name
        obj.get_forward_vector.return_value = vec(*forward)
        obj.get_up_vector.return_value = vec(0, 0, 1)
        obj.get_world_location.return_value = vec(*position)
        obj.get_editor_property.side_effect = (properties or {}).__getitem__
        return obj

    cam = {"projection_type": perspective, "texture_target": None, "fov_angle": 90.0}
    base = scene("base_link", (-100, 200, 0))
    left = scene("NavcamLeft", (-100, 200, 50), cam)
    right = scene("NavcamRight", (-100, 180, 50), cam)
    center = scene("NavcamCenter", (-100, 190, 50), cam)
    lidar = scene("Lidar", (-100, 200, 60),
                  {"follow_component_name": "None", "sensor_id": 1, "mode": "GPU"},
                  (0, 0, 0) if invalid_lidar else (-1, 0, 0))
    streamer = MagicMock()
    streamer.get_editor_property.side_effect = {
        "left_capture_name": "NavcamLeft", "right_capture_name": "NavcamRight",
        "center_capture_name": "NavcamCenter", "capture_width": 640, "capture_height": 480,
        "depth_cam_id": 4, "left_cam_id": 1, "right_cam_id": 2,
    }.__getitem__
    rover = MagicMock()
    rover.get_name.return_value = "ReferenceRover"
    lookup = {engine.SceneComponent: [base, left, right, center, lidar],
              engine.UnrealLidarCam: [lidar], engine.UnrealStereoCam: [streamer]}
    rover.get_components_by_class.side_effect = lookup.__getitem__
    return engine, rover, lidar, streamer


def test_invalid_lidar_mount_does_not_modify_components_or_write_config(tmp_path):
    m = setup()
    engine, rover, lidar, streamer = fake_rover_for_sensor_export(invalid_lidar=True)
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    output = tmp_path / "sensors.json"
    with pytest.raises(ValueError, match="orthonormal"):
        m.configure_and_export(engine, rover, manifest, output)
    lidar.set_editor_property.assert_not_called()
    streamer.set_editor_property.assert_not_called()
    assert not output.exists()


def test_valid_sensor_mounts_export_measured_rigid_transforms(tmp_path):
    from mars_rover.sensors import transform_matrix

    m = setup()
    engine, rover, lidar, streamer = fake_rover_for_sensor_export()
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    output = tmp_path / "sensors.json"
    assert m.configure_and_export(engine, rover, manifest, output) == str(output)
    config = json.loads(output.read_text())
    np.testing.assert_allclose(np.asarray(config["lidar"]["to_body"])[:3, 3], [0, 0, 0.6])
    for sensor in ("lidar", "depth", "stereo"):
        transform_matrix(config[sensor]["to_body"])
    assert config["stereo"]["baseline_m"] == pytest.approx(0.2)
    assert config["native_sensor_stream_verified"] is False
    assert config["native_rover_motion_verified"] is False
    lidar.set_editor_property.assert_any_call("server_port", 3007)
    streamer.set_editor_property.assert_any_call("server_port", 3004)


def test_runtime_sensor_plugins_are_explicitly_enabled_in_project():
    path = Path(__file__).parents[1] / "Moon_Simulator.uproject"
    enabled = {item["Name"] for item in json.loads(path.read_text())["Plugins"] if item.get("Enabled")}
    assert {"UnrealStereoCam", "UnrealLidarCam", "UnrealSimClock"} <= enabled
