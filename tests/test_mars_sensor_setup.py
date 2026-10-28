import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

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


def test_runtime_sensor_plugins_are_explicitly_enabled_in_project():
    path = Path(__file__).parents[1] / "Moon_Simulator.uproject"
    enabled = {item["Name"] for item in json.loads(path.read_text())["Plugins"] if item.get("Enabled")}
    assert {"UnrealStereoCam", "UnrealLidarCam", "UnrealSimClock"} <= enabled
