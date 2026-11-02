import builtins
from enum import Enum
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def module():
    path = Path(__file__).parents[1] / "Content/Python/mars_cpu_lidar_setup.py"
    spec = importlib.util.spec_from_file_location("cpu_lidar_setup_test", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class Mode(Enum):
    GPU = 0
    CPU = 1


class Component:
    def __init__(self, actor, values):
        self.actor, self.values = actor, dict(values)

    def get_editor_property(self, key):
        return self.values[key]

    def set_editor_property(self, key, value):
        if self.actor.fail_once == key:
            self.actor.fail_once = None
            raise RuntimeError("simulated edit failure")
        values = dict(self.values)
        values[key] = value
        if self.actor.reset_once == key:
            self.actor.reset_once = None
            values["horizontal_samples"] = 320
        if self.actor.guard_reset_once == key:
            self.actor.guard_reset_once = None
            values["follow_component_name"] = "Other"
        # Simulate Unreal replacing the live component during each edit. Old
        # Python wrappers remain readable but no longer represent the rover.
        self.actor.component = Component(self.actor, values)


class Actor:
    def __init__(self, values):
        self.component = Component(self, values)
        self.fail_once = None
        self.reset_once = None
        self.guard_reset_once = None

    def get_actor_label(self):
        return "Mars_Rover_Reference"

    def get_name(self):
        return "Reference"

    def get_components_by_class(self, _kind):
        return [self.component]


class FakeUnreal:
    UnrealLidarCamMode = Mode
    UnrealLidarCam = object()
    EditorActorSubsystem = object()

    def __init__(self):
        self.pie = False
        self.world_name = "/Game/Mars/Test.Test"
        self.original = {"mode": Mode.CPU, "send_cpu_capture_pose": False,
                         "horizontal_samples": 320, "channels": 240, "scan_rate_hz": 10.0}
        self.guard = {"sensor_id": 0, "server_ip": "127.0.0.1", "server_port": 3007,
                      "follow_component_name": "Navcam_Center"}
        self.actor = Actor({**self.original, **self.guard})
        self.actors = [self.actor]
        self.EditorLevelLibrary = SimpleNamespace(
            get_pie_worlds=lambda _: [object()] if self.pie else [],
            get_editor_world=lambda: SimpleNamespace(get_path_name=lambda: self.world_name),
        )

    def get_editor_subsystem(self, _kind):
        return self

    def get_all_level_actors(self):
        return self.actors


@pytest.fixture(autouse=True)
def clear_saved_state():
    key = "_mars_cpu_lidar_restore_state"
    if hasattr(builtins, key):
        delattr(builtins, key)
    yield
    if hasattr(builtins, key):
        delattr(builtins, key)


def test_reinstanced_components_are_resolved_after_every_edit_and_restored():
    m, engine = module(), FakeUnreal()
    previous_console = {**engine.original, "mode": Mode.GPU}
    report = m.apply(previous_console, _unreal=engine)
    assert report["runtime_verified"] is False
    assert report["level_saved"] is False
    assert report["restore_source"] == "previous_console_values"
    assert report["unchanged_sensor"]["follow_component_name"] == "Navcam_Center"
    assert engine.actor.component.values == {"mode": Mode.CPU, "send_cpu_capture_pose": True,
                                             "horizontal_samples": 160, "channels": 120, "scan_rate_hz": 5.0,
                                             **engine.guard}
    m.restore(_unreal=engine)
    assert engine.actor.component.values == {**previous_console, **engine.guard}


def test_pie_or_duplicate_actor_prevents_any_edits():
    m, engine = module(), FakeUnreal()
    engine.pie = True
    with pytest.raises(RuntimeError, match="Stop Play"):
        m.apply(_unreal=engine)
    assert engine.actor.component.values == {**engine.original, **engine.guard}
    engine.pie = False
    engine.actors.append(Actor({**engine.original, **engine.guard}))
    with pytest.raises(RuntimeError, match="exactly one"):
        m.apply(_unreal=engine)
    assert engine.actor.component.values == {**engine.original, **engine.guard}


@pytest.mark.parametrize("problem", ["fail", "reset", "guard"])
def test_failed_or_reverted_property_restores_original_settings(problem):
    m, engine = module(), FakeUnreal()
    if problem == "fail":
        engine.actor.fail_once = "channels"
    elif problem == "reset":
        engine.actor.reset_once = "channels"
    else:
        engine.actor.guard_reset_once = "channels"
    with pytest.raises(RuntimeError, match="previous editor settings restored"):
        m.apply(_unreal=engine)
    assert engine.actor.component.values == {**engine.original, **engine.guard}
    assert not hasattr(builtins, "_mars_cpu_lidar_restore_state")


def test_restore_refuses_a_different_world_or_running_play():
    m, engine = module(), FakeUnreal()
    m.apply(_unreal=engine)
    configured = dict(engine.actor.component.values)
    engine.pie = True
    with pytest.raises(RuntimeError, match="Stop Play"):
        m.restore(_unreal=engine)
    engine.pie = False
    engine.world_name = "/Game/Mars/Other.Other"
    with pytest.raises(RuntimeError, match="world or reference rover changed"):
        m.restore(_unreal=engine)
    assert engine.actor.component.values == configured
