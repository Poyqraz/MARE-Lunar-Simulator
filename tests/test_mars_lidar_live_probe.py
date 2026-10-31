"""The idle probe compares display samples and never commands the rover."""

import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from contextlib import redirect_stdout

import numpy as np

from mars_rover.sensors import pose_from_telemetry


ROOT = Path(__file__).resolve().parents[1]


def module():
    python_path = str(ROOT / "Content/Python")
    if python_path not in sys.path:
        sys.path.insert(0, python_path)
    spec = importlib.util.spec_from_file_location("mars_lidar_live_probe", ROOT / "Content/Python/mars_lidar_live_probe.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def fake_world():
    calls = []

    class SceneComponent:
        def __init__(self, name, xyz):
            self.name, self.xyz = name, xyz

        def get_name(self):
            return self.name

        def get_forward_vector(self):
            return SimpleNamespace(x=-1.0, y=0.0, z=0.0)

        def get_up_vector(self):
            return SimpleNamespace(x=0.0, y=0.0, z=1.0)

        def get_world_location(self):
            return SimpleNamespace(x=self.xyz[0], y=self.xyz[1], z=self.xyz[2])

    class Lidar:
        def get_editor_property(self, name):
            return {"follow_component_name": "Navcam_Center", "mode": "GPU", "sensor_id": 0}[name]

    class Actor:
        def get_name(self):
            return "Leo_Raph_C_0"

        def get_class(self):
            return SimpleNamespace(get_name=lambda: "Leo_Raph_C")

        def get_components_by_class(self, component_class):
            if component_class is SceneComponent:
                return [SceneComponent("base_link", (-10000, 10000, 100)),
                        SceneComponent("Navcam_Center", (-10000, 10000, 150))]
            return [Lidar()]

    class Landscape:
        def get_name(self):
            return "Landscape_0"

        def get_class(self):
            return SimpleNamespace(get_name=lambda: "Landscape")

    class Hit:
        def to_tuple(self):
            fields = [None] * 18
            fields[0], fields[5], fields[9] = True, SimpleNamespace(z=20.0), Landscape()
            return tuple(fields)

    def trace(**kwargs):
        calls.append(kwargs)
        return Hit()

    rover = Actor()
    world = SimpleNamespace(get_path_name=lambda: "/Game/Mars/UEDPIE_0_Test.Test")
    return SimpleNamespace(
        EditorLevelLibrary=SimpleNamespace(get_pie_worlds=lambda _: [world]),
        GameplayStatics=SimpleNamespace(get_all_actors_of_class=lambda _w, _c: [rover]),
        SceneComponent=SceneComponent, UnrealLidarCam=Lidar, Pawn=object,
        Vector=lambda x, y, z: SimpleNamespace(x=x, y=y, z=z),
        SystemLibrary=SimpleNamespace(line_trace_single=trace),
        TraceTypeQuery=SimpleNamespace(TRACE_TYPE_QUERY1="visibility"),
        DrawDebugTrace=SimpleNamespace(NONE="none"),
    ), calls


def api(state="idle", lag_ns=100_000_000, wheel=0.0, angular=0.0, telemetry_age=0.01):
    stamp = 1_700_000_000_000_000_000
    telemetry = {"x": -10000, "y": 10000, "z": 100, "roll": 0, "pitch": 0, "yaw": 180,
                 "wx": angular, "wy": 0, "wz": 0, "t_ns": str(stamp)}
    snapshot = {"state": state, "pose_fresh": True, "capture_clock_advancing": True, "speed_estimate_m_s": 0.001}
    status = {"connected": True, "connection_id": 7, "telemetry_age_s": telemetry_age,
              "wheel_command_m_s": {k: wheel for k in ("FL", "FR", "BL", "BR")},
              "telemetry_unreal": telemetry}
    scan = {"frame": "rover", "stamp_ns": str(stamp - lag_ns), "count": 3,
            "points": [4, 0, -1, 5.5, 0, -1, 7, 0, -1]}
    seen = []

    def fetch(url):
        seen.append(url)
        return {"http://127.0.0.1:8766/mission/snapshot": snapshot,
                "http://127.0.0.1:8765/status": status,
                "http://127.0.0.1:8766/dashboard/lidar": scan}[url]

    return fetch, seen


def config_file(tmp_path):
    path = tmp_path / "sensors.json"
    path.write_text(json.dumps({"lidar": {"sensor_id": 0, "to_body": [[1, 0, 0, 0], [0, 1, 0, 0],
                                                     [0, 0, 1, 0.5], [0, 0, 0, 1]]}}))
    return path


class TestLidarLiveProbe(unittest.TestCase):
    def test_idle_probe_compares_current_body_points_with_collision(self):
        probe = module()
        unreal, calls = fake_world()
        fetch, seen = api()
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(output):
            result = probe.probe_idle(str(config_file(Path(tmp))), unreal_module=unreal, fetch_json=fetch)

        self.assertEqual(len(calls), 3)
        self.assertAlmostEqual(calls[0]["start"].x, -10400)
        self.assertAlmostEqual(calls[0]["start"].y, 10000)
        self.assertTrue(calls[0]["trace_complex"])
        self.assertEqual(len(calls[0]["actors_to_ignore"]), 1)
        self.assertAlmostEqual(result["runtime_sensor_matrix_max_difference"], 0)
        self.assertAlmostEqual(result["telemetry_vs_current_body"]["distance_m"], 0)
        self.assertAlmostEqual(result["telemetry_vs_current_body"]["rotation_deg"], 0)
        self.assertAlmostEqual(result["scan_to_telemetry_s"], 0.1)
        self.assertEqual([b["landscape_hits"] for b in result["range_bins"]], [1, 1, 1])
        for item in result["range_bins"]:
            self.assertAlmostEqual(item["median_lidar_minus_collision_m"], -0.2)
            self.assertEqual(item["below_minus_015m"], 1)
        self.assertIn("MARS_LIDAR_IDLE_PROBE:", output.getvalue())
        self.assertTrue(all(url.startswith("http://127.0.0.1:") for url in seen))
        self.assertTrue(all(not any(x in url for x in ("/goal", "/stop", "/command")) for url in seen))

    def test_probe_rejects_motion_or_stale_scan_before_any_trace(self):
        probe = module()
        unreal, calls = fake_world()
        cases = ((api(state="following")[0], "idle"), (api(lag_ns=500_000_000)[0], "behind pose"),
                 (api(wheel=0.1)[0], "wheel command"), (api(angular=0.1)[0], "angular velocity"),
                 (api(telemetry_age=0.41)[0], "telemetry became too old"))
        for fetch, expected in cases:
            with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(ValueError, expected):
                probe.probe_idle(str(config_file(Path(tmp))), unreal_module=unreal, fetch_json=fetch)
        self.assertEqual(calls, [])

    def test_stdlib_telemetry_pose_matches_navigation_pose_for_nonzero_angles(self):
        probe = module()
        telemetry = {"x": -12000.1, "y": 13000.2, "z": 543.0, "roll": -3.1, "pitch": 4.7, "yaw": -92.2,
                     "t_ns": "1700000000000000000"}
        np.testing.assert_allclose(probe._telemetry_pose(telemetry), pose_from_telemetry(telemetry).matrix[:3],
                                   atol=1e-14)


if __name__ == "__main__":
    unittest.main()
