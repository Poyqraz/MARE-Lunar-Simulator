"""Temporarily configure the placed rover's CPU LiDAR, before Play only.

Editor property edits can reinstance a Blueprint component. Re-resolve the
actor and component for every edit, then verify the current component rather
than a previously held Python wrapper. Nothing here saves the level or
changes any Play-world object.
"""

import builtins
import json
import math


_STATE_KEY = "_mars_cpu_lidar_restore_state"
_PROPERTIES = ("send_cpu_capture_pose", "horizontal_samples", "channels", "scan_rate_hz", "mode")
_GUARDS = ("sensor_id", "server_ip", "server_port", "follow_component_name")


def _engine(override):
    if override is not None:
        return override
    import unreal
    return unreal


def _current(unreal, identity=None):
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError("Stop Play before changing editor sensor settings")
    world = unreal.EditorLevelLibrary.get_editor_world()
    if world is None:
        raise RuntimeError("No editor world is open")
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    rovers = [actor for actor in actors if actor.get_actor_label() == "Mars_Rover_Reference"]
    if len(rovers) != 1:
        raise RuntimeError("Expected exactly one Mars_Rover_Reference actor")
    rover = rovers[0]
    current_identity = (world.get_path_name(), rover.get_name())
    if identity is not None and current_identity != identity:
        raise RuntimeError("Editor world or reference rover changed")
    sensors = rover.get_components_by_class(unreal.UnrealLidarCam)
    if len(sensors) != 1:
        raise RuntimeError("Expected exactly one LiDAR on the reference rover")
    return current_identity, sensors[0]


def _read(unreal, identity, names=_PROPERTIES):
    # Reading does not alter components, but still resolve the current one.
    _, sensor = _current(unreal, identity)
    return {name: sensor.get_editor_property(name) for name in names}


def _same(actual, expected):
    if isinstance(expected, float):
        return isinstance(actual, (float, int)) and math.isfinite(actual) and math.isclose(
            float(actual), expected, rel_tol=0, abs_tol=1e-5
        )
    return actual == expected


def _validate_values(unreal, values):
    if not isinstance(values, dict) or set(values) != set(_PROPERTIES):
        raise ValueError("Restore settings must contain exactly the five LiDAR test properties")
    if values["mode"] not in (unreal.UnrealLidarCamMode.CPU, unreal.UnrealLidarCamMode.GPU):
        raise ValueError("Invalid LiDAR mode in restore settings")
    if type(values["send_cpu_capture_pose"]) is not bool:
        raise ValueError("Invalid capture-pose flag in restore settings")
    for key, maximum in (("horizontal_samples", 4096), ("channels", 512)):
        if type(values[key]) is not int or not 1 <= values[key] <= maximum:
            raise ValueError(f"Invalid {key} in restore settings")
    rate = values["scan_rate_hz"]
    if type(rate) not in (int, float) or not math.isfinite(rate) or not 0.1 <= rate <= 50:
        raise ValueError("Invalid scan rate in restore settings")


def _apply_verified(unreal, identity, values, *, names=_PROPERTIES, guards=None):
    checked = {}
    for key in names:
        _, sensor = _current(unreal, identity)
        if not _same(sensor.get_editor_property(key), values[key]):
            sensor.set_editor_property(key, values[key])
        checked[key] = values[key]
        # A later post-edit reconstruction must not silently undo earlier edits.
        actual = _read(unreal, identity, names)
        for name, expected in checked.items():
            if not _same(actual[name], expected):
                raise RuntimeError(f"LiDAR property {name} did not persist on the current component")
        if guards is not None:
            current_guards = _read(unreal, identity, _GUARDS)
            for name, expected in guards.items():
                if not _same(current_guards[name], expected):
                    raise RuntimeError(f"Unrelated LiDAR property {name} changed during setup")
    return _read(unreal, identity, names)


def _transition(unreal, identity, desired):
    before = _read(unreal, identity)
    guards = _read(unreal, identity, _GUARDS)
    try:
        return _apply_verified(unreal, identity, desired, guards=guards)
    except Exception as error:
        try:
            _apply_verified(unreal, identity, {**before, **guards}, names=_PROPERTIES + _GUARDS)
        except Exception as rollback_error:
            raise RuntimeError(f"LiDAR setting failed; restoration is incomplete: {rollback_error}") from error
        raise RuntimeError(f"LiDAR setting failed; previous editor settings restored: {error}") from error


def _printable(values):
    return {key: str(value) if key == "mode" else value for key, value in values.items()}


def apply(restore_values=None, *, _unreal=None):
    """Set test values; optional restore_values may preserve an earlier state."""
    unreal = _engine(_unreal)
    if getattr(builtins, _STATE_KEY, None) is not None:
        raise RuntimeError("CPU LiDAR test settings already active; restore them first")
    identity, _ = _current(unreal)
    before = _read(unreal, identity)
    _validate_values(unreal, before)
    original = dict(before if restore_values is None else restore_values)
    _validate_values(unreal, original)
    desired = {"send_cpu_capture_pose": True, "horizontal_samples": 160, "channels": 120,
               "scan_rate_hz": 5.0, "mode": unreal.UnrealLidarCamMode.CPU}
    actual = _transition(unreal, identity, desired)
    setattr(builtins, _STATE_KEY, {"identity": identity, "values": original})
    result = {"world": identity[0], "rover": identity[1], "settings": _printable(actual),
              "unchanged_sensor": {key: str(value) for key, value in _read(unreal, identity, _GUARDS).items()},
              "restore_source": "previous_console_values" if restore_values is not None else "before_apply",
              "level_saved": False, "runtime_verified": False}
    print("MARS_CPU_LIDAR_EDITOR: " + json.dumps(result, ensure_ascii=False))
    return result


def restore(*, _unreal=None):
    """Restore saved editor settings after Play has stopped, without saving."""
    unreal = _engine(_unreal)
    state = getattr(builtins, _STATE_KEY, None)
    if state is None:
        raise RuntimeError("No saved CPU LiDAR test settings in this editor session")
    _validate_values(unreal, state["values"])
    actual = _transition(unreal, state["identity"], state["values"])
    delattr(builtins, _STATE_KEY)
    result = {"world": state["identity"][0], "rover": state["identity"][1],
              "settings": _printable(actual), "level_saved": False}
    print("MARS_CPU_LIDAR_RESTORED: " + json.dumps(result, ensure_ascii=False))
    return result
