"""The opt-in PIE mount observer measures geometry and never sends commands."""

import builtins
import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def module(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "Content/Python"))
    spec = importlib.util.spec_from_file_location(
        "mars_lidar_mount_diagnostics", ROOT / "Content/Python/mars_lidar_mount_diagnostics.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    monkeypatch.delattr(builtins, result._KEY, raising=False)
    return result


class Component:
    def __init__(self, name):
        self.name, self.yaw = name, 0.0
        self.position = (0.0, 0.0, 0.0)

    def get_name(self):
        return self.name

    def get_forward_vector(self):
        return SimpleNamespace(x=math.cos(self.yaw), y=math.sin(self.yaw), z=0.0)

    def get_up_vector(self):
        return SimpleNamespace(x=0.0, y=0.0, z=1.0)

    def get_world_location(self):
        return SimpleNamespace(x=self.position[0], y=self.position[1], z=self.position[2])


class Simulator:
    def __init__(self):
        self.time, self.active, self.callbacks, self.unregistered = 0.0, True, {}, []
        self.get_calls = 0
        self.world = SimpleNamespace(get_path_name=lambda: "/Game/Mars/UEDPIE_0_Test.Test")
        self.body, self.mount = Component("base_link"), Component("Navcam_Center")
        self.lidar = SimpleNamespace(get_editor_property=lambda name: {"follow_component_name": "Navcam_Center",
                                                                       "sensor_id": 0}[name])
        self.rover = SimpleNamespace(get_name=lambda: "Leo_Raph_C_0",
                                     get_class=lambda: SimpleNamespace(get_name=lambda: "Leo_Raph_C"),
                                     get_components_by_class=self.components)
        self.unreal = SimpleNamespace(
            Pawn=object(), UnrealLidarCam=object(), SceneComponent=object(),
            EditorLevelLibrary=SimpleNamespace(get_pie_worlds=lambda _: [self.world] if self.active else []),
            GameplayStatics=SimpleNamespace(get_all_actors_of_class=lambda _w, _t: [self.rover]),
            GncSimTimeLibrary=SimpleNamespace(get_sim_time_ns_string=lambda _w: str(1700000000000000000
                                                                                   + int(self.time * 1e9))),
            register_slate_post_tick_callback=self.register,
            unregister_slate_post_tick_callback=self.unregister,
        )

    def components(self, cls):
        return [self.lidar] if cls is self.unreal.UnrealLidarCam else [self.body, self.mount]

    def register(self, callback):
        self.callbacks[7] = callback
        return 7

    def unregister(self, handle):
        self.unregistered.append(handle)
        del self.callbacks[handle]

    def snapshot(self):
        self.get_calls += 1
        return {"session_id": "session-a", "state": "idle", "mission": None,
                "terrain_manifest_sha256": "manifest-a",
                "position_source": "simulation telemetry", "pose_fresh": True, "capture_clock_advancing": True,
                "speed_estimate_m_s": 0.0, "wheel_command_m_s": dict.fromkeys(("FL", "FR", "BL", "BR"), 0.0)}

    def tick(self, t):
        self.time = t
        self.callbacks[7](0.0)


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "sensors.json"
    path.write_text(json.dumps({"schema_version": 1, "manifest_sha256": "manifest-a", "lidar": {"sensor_id": 0,
                                          "to_body": [[1, 0, 0, 0], [0, 1, 0, 0],
                                                      [0, 0, 1, 0], [0, 0, 0, 1]]}}), encoding="utf-8")
    return path


def alignment():
    return {"session_id": "session-a", "world": "/Game/Mars/UEDPIE_0_Test.Test", "rover": "Leo_Raph_C_0"}


def test_observes_relative_mount_through_rover_rotation_and_saves_bounded_report(monkeypatch, config_path):
    mod, sim = module(monkeypatch), Simulator()
    result = mod.start(config_path, alignment(), unreal_module=sim.unreal,
                       get_snapshot=sim.snapshot, monotonic=lambda: sim.time)
    assert result["started"] and sim.get_calls == 1
    sim.body.yaw = sim.mount.yaw = 0.5
    sim.tick(0.11)
    sim.mount.yaw += 0.1
    sim.tick(0.22)
    summary = mod.stop()
    assert summary["sample_count"] == 3
    assert summary["unique_stamp_count"] == 3
    assert summary["max_heading_change_deg"] == pytest.approx(math.degrees(0.5))
    assert summary["max_mount_translation_difference_m"] == pytest.approx(0)
    assert summary["max_mount_rotation_difference_deg"] == pytest.approx(math.degrees(0.1))
    assert summary["max_mount_rotation_change_from_first_deg"] == pytest.approx(math.degrees(0.1))
    assert sim.get_calls == 1  # No HTTP in any callback or stop.
    assert sim.unregistered == [7] and not sim.callbacks
    report = json.loads(Path(summary["report_path"]).read_text(encoding="utf-8"))
    assert len(report["samples"]) == 3
    assert report["samples"][-1]["stamp_ns"] == "1700000000220000000"


def test_rigid_offset_mount_does_not_look_like_motion_when_body_turns(monkeypatch, config_path):
    mod, sim = module(monkeypatch), Simulator()
    sim.mount.yaw = math.radians(20)
    sim.mount.position = (18.5, 0.0, 55.0)  # Unreal centimetres.
    data = json.loads(config_path.read_text(encoding="utf-8"))
    data["lidar"]["to_body"] = mod.frames.relative_frame(mod.frames.map_frame(sim.body),
                                                           mod.frames.map_frame(sim.mount))
    config_path.write_text(json.dumps(data), encoding="utf-8")
    mod.start(config_path, alignment(), unreal_module=sim.unreal,
              get_snapshot=sim.snapshot, monotonic=lambda: sim.time)
    sim.body.yaw = 0.5
    sim.mount.yaw = 0.5 + math.radians(20)
    sim.mount.position = (18.5 * math.cos(0.5), 18.5 * math.sin(0.5), 55.0)
    sim.tick(0.11)
    summary = mod.stop()
    assert summary["max_heading_change_deg"] == pytest.approx(math.degrees(0.5))
    assert summary["max_mount_translation_change_from_first_m"] < 1e-12
    assert summary["max_mount_rotation_change_from_first_deg"] < 1e-5


def test_auto_stops_on_play_end_without_calling_service(monkeypatch, config_path):
    mod, sim = module(monkeypatch), Simulator()
    mod.start(config_path, alignment(), unreal_module=sim.unreal,
              get_snapshot=sim.snapshot, monotonic=lambda: sim.time)
    sim.active = False
    sim.tick(0.2)
    assert sim.unregistered == [7] and sim.get_calls == 1
    reports = list(config_path.parent.glob("lidar-montaj-*.json"))
    assert len(reports) == 1
    assert json.loads(reports[0].read_text(encoding="utf-8"))["summary"]["reason"] == "play_world_changed"


def test_observer_times_out_and_unregisters_without_blocking_on_service(monkeypatch, config_path):
    mod, sim = module(monkeypatch), Simulator()
    mod.start(config_path, alignment(), duration_s=1, unreal_module=sim.unreal,
              get_snapshot=sim.snapshot, monotonic=lambda: sim.time)
    sim.tick(1.1)
    assert sim.unregistered == [7] and sim.get_calls == 1
    reports = list(config_path.parent.glob("lidar-montaj-*.json"))
    assert len(reports) == 1
    assert json.loads(reports[0].read_text(encoding="utf-8"))["summary"]["reason"] == "duration_or_sample_limit"


@pytest.mark.parametrize("error", ["session", "speed", "clock", "world", "sensor_id", "manifest", "bad_matrix"])
def test_rejects_invalid_start_without_registering_callback(monkeypatch, config_path, error):
    mod, sim = module(monkeypatch), Simulator()
    a = alignment()
    snapshot = sim.snapshot()
    if error == "session":
        a["session_id"] = "different"
    elif error == "speed":
        snapshot["speed_estimate_m_s"] = 0.1
    elif error == "clock":
        snapshot["capture_clock_advancing"] = False
    elif error == "world":
        a["world"] = "different"
    elif error == "manifest":
        snapshot["terrain_manifest_sha256"] = "different"
    elif error == "sensor_id":
        data = json.loads(config_path.read_text(encoding="utf-8"))
        data["lidar"]["sensor_id"] = 5
        config_path.write_text(json.dumps(data), encoding="utf-8")
    else:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        data["lidar"]["to_body"][0][0] = -1
        config_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        mod.start(config_path, a, unreal_module=sim.unreal, get_snapshot=lambda: snapshot,
                  monotonic=lambda: sim.time)
    assert not sim.callbacks and getattr(builtins, mod._KEY, None) is None
