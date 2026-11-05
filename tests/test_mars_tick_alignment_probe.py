"""PIE-only timing experiment: preflight, targeting and rollback."""

from contextlib import redirect_stdout
import copy
import importlib.util
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Content/Python"))
spec = importlib.util.spec_from_file_location("mars_tick_alignment_probe", ROOT / "Content/Python/mars_tick_alignment_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class Tick:
    def __init__(self, group):
        self.group = group

    def get_editor_property(self, name):
        if name != "tick_group":
            raise AssertionError(name)
        return self.group


class Component:
    def __init__(self, name, group):
        self.name, self.tick = name, Tick(group)
        self.enabled = True
        self.fail_on = set()
        self.ignore_updates = False
        self.calls = []

    def get_name(self):
        return self.name

    def get_editor_property(self, name):
        if name not in ("primary_actor_tick", "primary_component_tick"):
            raise AssertionError(name)
        return self.tick

    def set_tick_group(self, group):
        self.calls.append(group)
        if group in self.fail_on:
            raise RuntimeError("mock tick failure")
        if not self.ignore_updates:
            self.tick.group = group

    def is_component_tick_enabled(self):
        return self.enabled


class Rover(Component):
    def __init__(self, lidar, camera, rear):
        super().__init__("Leo_Raph_C_0", "pre")
        self.lidar, self.camera, self.rear = lidar, camera, rear

    def is_actor_tick_enabled(self):
        return self.enabled

    def get_class(self):
        return SimpleNamespace(get_name=lambda: "Leo_Raph_C")

    def get_components_by_class(self, kind):
        return [self.lidar] if kind == "lidar_class" else [self.camera, self.rear]


def sim():
    lidar, camera, rear = Component("Lidar", "post"), Component("NavCam_UnrealStereoCam", "pre"), Component("RearCam_Stream", "pre")
    rover = Rover(lidar, camera, rear)
    world = SimpleNamespace(get_path_name=lambda: "/Game/Mars/UEDPIE_0_Test.Test")
    unreal = SimpleNamespace(
        EditorLevelLibrary=SimpleNamespace(get_pie_worlds=lambda _: [world]),
        GameplayStatics=SimpleNamespace(get_all_actors_of_class=lambda _w, _c: [rover]),
        Pawn=object, UnrealLidarCam="lidar_class", UnrealStereoCam="camera_class",
        TickingGroup=SimpleNamespace(TG_POST_PHYSICS="post", TG_POST_UPDATE_WORK="later"),
    )
    wheels = dict.fromkeys(("FL", "FR", "BL", "BR"), 0.0)
    snapshot = {"session_id": "session", "state": "idle", "pose_fresh": True, "capture_clock_advancing": True,
                "position_source": "simulation telemetry", "mission": None, "speed_estimate_m_s": 0.001,
                "wheel_command_m_s": wheels, "live_pose": {"stamp_ns": "1700000000000000000"}}
    bridge = {"connected": True, "telemetry_format": "unreal-tr-v1", "telemetry_age_s": 0.05,
              "wheel_command_m_s": copy.deepcopy(wheels),
              "telemetry_unreal": {"wx": 0.0, "wy": 0.0, "wz": 0.0, "t_ns": "1700000000000000000"}}

    def get_json(url):
        return snapshot if ":8766/" in url else bridge

    return unreal, rover, lidar, camera, rear, snapshot, bridge, get_json


class TestTickAlignmentProbe(unittest.TestCase):
    def test_changes_only_target_pie_actor_and_navigation_components(self):
        unreal, rover, lidar, camera, rear, _, _, get = sim()
        with redirect_stdout(io.StringIO()) as output:
            result = probe.apply(unreal_module=unreal, get_json=get)
        self.assertEqual((rover.tick.group, lidar.tick.group, camera.tick.group, rear.tick.group),
                         ("post", "later", "later", "pre"))
        self.assertEqual(result["groups"]["actor"], {"before": "pre", "after": "post"})
        self.assertEqual(result["session_id"], "session")
        self.assertIn("MARS_TICK_ALIGNMENT:", output.getvalue())

    def test_unready_or_moving_rover_never_changes_groups(self):
        for case in ("mission", "pose", "speed", "wheel", "bridge_wheel", "angular", "clock", "disconnected"):
            unreal, rover, lidar, camera, _, snapshot, bridge, get = sim()
            if case == "mission": snapshot["mission"] = {"closed": False}
            if case == "pose": snapshot["pose_fresh"] = False
            if case == "speed": snapshot["speed_estimate_m_s"] = 0.02
            if case == "wheel": snapshot["wheel_command_m_s"]["FL"] = 0.1
            if case == "bridge_wheel": bridge["wheel_command_m_s"]["FR"] = 0.1
            if case == "angular": bridge["telemetry_unreal"]["wz"] = 0.1
            if case == "clock": bridge["telemetry_unreal"]["t_ns"] = "1700000001000000000"
            if case == "disconnected": bridge["connected"] = False
            with self.subTest(case=case), self.assertRaises(ValueError):
                probe.apply(unreal_module=unreal, get_json=get)
            self.assertEqual((rover.calls, lidar.calls, camera.calls), ([], [], []))

    def test_failed_component_change_restores_previous_tick_groups(self):
        unreal, rover, lidar, camera, _, _, _, get = sim()
        camera.fail_on.add("later")
        with self.assertRaisesRegex(RuntimeError, "mock tick failure"):
            probe.apply(unreal_module=unreal, get_json=get)
        self.assertEqual((rover.tick.group, lidar.tick.group, camera.tick.group), ("pre", "post", "pre"))

    def test_interrupt_during_change_restores_previous_tick_groups(self):
        unreal, rover, lidar, camera, _, _, _, get = sim()
        setter = camera.set_tick_group

        def interrupt(group):
            if group == "later":
                raise KeyboardInterrupt()
            setter(group)

        camera.set_tick_group = interrupt
        with self.assertRaises(KeyboardInterrupt):
            probe.apply(unreal_module=unreal, get_json=get)
        self.assertEqual((rover.tick.group, lidar.tick.group, camera.tick.group), ("pre", "post", "pre"))

    def test_rollback_failure_requests_stopping_play(self):
        unreal, rover, lidar, camera, _, _, _, get = sim()
        camera.fail_on.add("later")
        lidar.fail_on.add("post")
        with self.assertRaisesRegex(RuntimeError, "stop Unreal Play"):
            probe.apply(unreal_module=unreal, get_json=get)
        self.assertEqual(rover.tick.group, "pre")

    def test_readback_mismatch_rolls_back_and_missing_camera_is_rejected(self):
        unreal, rover, lidar, camera, _, _, _, get = sim()
        camera.ignore_updates = True
        with self.assertRaisesRegex(RuntimeError, "did not update"):
            probe.apply(unreal_module=unreal, get_json=get)
        self.assertEqual((rover.tick.group, lidar.tick.group, camera.tick.group), ("pre", "post", "pre"))
        camera.name = "other"
        with self.assertRaisesRegex(ValueError, "NavCam"):
            probe.apply(unreal_module=unreal, get_json=get)

    def test_no_pie_world_or_disabled_sensor_is_rejected(self):
        unreal, rover, lidar, camera, _, _, _, get = sim()
        unreal.EditorLevelLibrary.get_pie_worlds = lambda _: []
        with self.assertRaisesRegex(ValueError, "one local"):
            probe.apply(unreal_module=unreal, get_json=get)
        unreal, rover, lidar, camera, _, _, _, get = sim()
        camera.enabled = False
        with self.assertRaisesRegex(ValueError, "ticks must be enabled"):
            probe.apply(unreal_module=unreal, get_json=get)
        self.assertEqual((rover.calls, lidar.calls, camera.calls), ([], [], []))


if __name__ == "__main__":
    unittest.main()
