import json
import math
from types import SimpleNamespace

import numpy as np
import pytest

from mars_rover import nav_service
from mars_rover.navigation import DEFAULT_ANGULAR_LIMIT_RAD_S, NavigationSession
from mars_rover.planning import PlanningLimits, TerrainMap
from mars_rover.sensors import CameraFrame, LidarScan


@pytest.fixture
def scene():
    grid = TerrainMap(np.zeros((20, 20)), 1, PlanningLimits(robot_radius_m=0))
    config = {
        "schema_version": 1,
        "manifest_sha256": None,
        "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
        "depth": {
            "camera_id": 4,
            "hfov_deg": 90,
            "to_body": [[0, 0, 1, 0], [-1, 0, 0, 0], [0, -1, 0, 1], [0, 0, 0, 1]],
        },
    }
    return grid, config


@pytest.mark.parametrize("limit", [DEFAULT_ANGULAR_LIMIT_RAD_S, math.radians(20)])
@pytest.mark.parametrize("stop_kind", ["stale", "manual"])
def test_navigation_applies_turn_limit_and_stops(scene, limit, stop_kind):
    grid, config = scene
    session = NavigationSession(grid, config, min_points=1, settle_s=0, angular_limit_rad_s=limit)
    session.set_goal((5, 10))
    stamp = 1700000000000000000
    status = {
        "connected": True,
        "connection_id": 1,
        "telemetry_age_s": 0,
        "telemetry_unreal": dict(x=-500, y=500, z=0, roll=0, pitch=0, yaw=180, t_ns=str(stamp)),
    }
    assert session.step(status, now=1) == (0, 0)
    session.feed_lidar(LidarScan(0, 1, stamp, np.array([[2.0, 0, 0]]), 1, 1), now=1)
    depth = np.full((3, 3), np.nan, dtype="float32")
    depth[2, 1] = 150
    session.feed_camera(CameraFrame(4, 1, stamp, 2, depth), now=1)
    assert session.step(status, now=1.01) == (0, 0)  # plan while stopped
    velocity, angular = session.step(status, now=1.02)
    assert velocity == 0
    assert angular == pytest.approx(limit)
    if stop_kind == "manual":
        session.stop()
        assert session.step(status, now=1.03) == (0, 0)
    else:
        assert session.step(status, now=2) == (0, 0)  # stale observations stop immediately


@pytest.mark.parametrize("limit", [0, -0.1, 0.60001, float("nan"), float("inf"), True, None, "0.2"])
def test_navigation_rejects_invalid_or_above_existing_turn_limit(scene, limit):
    grid, config = scene
    with pytest.raises(ValueError):
        NavigationSession(grid, config, angular_limit_rad_s=limit)


@pytest.mark.parametrize("extra,expected", [([], DEFAULT_ANGULAR_LIMIT_RAD_S),
                                             (["--max-turn-rate-deg-s", "20"], math.radians(20))])
def test_cli_passes_opt_in_limit_to_service(monkeypatch, tmp_path, extra, expected):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({}), encoding="utf-8")
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
    nav_service.main(["--sensors", str(config), *extra])
    assert seen["angular_limit_rad_s"] == pytest.approx(expected)


@pytest.mark.parametrize("invalid", ["0", "-1", "35", "nan", "inf"])
def test_cli_rejects_invalid_turn_limit_before_opening_sensors(invalid):
    with pytest.raises(SystemExit) as error:
        nav_service.main(["--sensors", "not-opened.json", "--max-turn-rate-deg-s", invalid])
    assert error.value.code == 2
