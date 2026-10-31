"""The editor probe checks recorded obstacle coordinates without modifying a level."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def module():
    path = Path(__file__).resolve().parents[1] / "Content/Python/mars_lidar_collision_probe.py"
    spec = importlib.util.spec_from_file_location("mars_lidar_collision_probe", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def incident():
    return {
        "session_id": "s1",
        "missions": [{"mission_id": "m1", "goal": [126.0, 134.0]}],
        "obstacle_diagnostics": {
            "enabled": True, "frames_evicted": 0,
            "last_planning_failure": {"mission_id": "m1", "goal": {"blocked": True,
                                     "contributors_raw_row_col": [[134, 126], [133, 126]]}},
            "frames": [{"frame_id": 42, "source": "lidar", "stamp_ns": "123", "new_cells_truncated": 0,
                        "new_cells": [{"cell_row_col": [134, 126], "sample_world_m": [125.5, 133.9, 5.07],
                                       "sample_residual_m": -0.23}]}],
        },
    }


def fake_unreal():
    calls = []

    class Actor:
        def get_name(self):
            return "Mars_Jezero_MeasuredTerrain"

        def get_class(self):
            return SimpleNamespace(get_name=lambda: "Landscape")

    class Hit:
        def to_tuple(self):
            fields = [None] * 18
            fields[0], fields[5], fields[9] = True, SimpleNamespace(x=-12550, y=13390, z=530.0), Actor()
            return tuple(fields)

    def trace(**kwargs):
        calls.append(kwargs)
        return Hit()

    world = SimpleNamespace(get_path_name=lambda: "/Game/Mars/Test.Test")
    unreal = SimpleNamespace(
        EditorLevelLibrary=SimpleNamespace(get_pie_worlds=lambda _: [world], get_editor_world=lambda: world),
        SystemLibrary=SimpleNamespace(line_trace_single=trace),
        Vector=lambda x, y, z: SimpleNamespace(x=x, y=y, z=z),
        TraceTypeQuery=SimpleNamespace(TRACE_TYPE_QUERY1="visibility"),
        DrawDebugTrace=SimpleNamespace(NONE="none"),
    )
    return unreal, calls


def test_probe_uses_recorded_sample_and_reports_both_collision_modes(tmp_path):
    report = tmp_path / "incident.json"
    report.write_text(json.dumps(incident()), encoding="utf-8")
    unreal, calls = fake_unreal()
    result = module().probe_goal(str(report), unreal_module=unreal)
    assert result["world_type"] == "PIE"
    assert result["mission_id"] == "m1"
    assert result["missing_contributors"] == [[133, 126]]
    assert len(calls) == 2
    assert [c["trace_complex"] for c in calls] == [False, True]
    assert calls[0]["start"].x == pytest.approx(-12550)
    assert calls[0]["start"].y == pytest.approx(13390)
    sample = result["samples"][0]
    assert sample["dem_z_m"] == pytest.approx(5.3)
    assert sample["traces"]["simple"]["collision_z_m"] == pytest.approx(5.3)
    assert sample["traces"]["simple"]["collision_vs_dem_m"] == pytest.approx(0)
    assert sample["traces"]["complex"]["actor_class"] == "Landscape"


def test_probe_refuses_an_unblocked_goal_or_ambiguous_pie_world(tmp_path):
    report = incident()
    report["obstacle_diagnostics"]["last_planning_failure"]["goal"]["blocked"] = False
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    unreal, _ = fake_unreal()
    with pytest.raises(ValueError, match="blocked goal"):
        module().probe_goal(str(path), unreal_module=unreal)

    path.write_text(json.dumps(incident()), encoding="utf-8")
    unreal.EditorLevelLibrary.get_pie_worlds = lambda _: ["world1", "world2"]
    with pytest.raises(RuntimeError, match="PIE worlds"):
        module().probe_goal(str(path), unreal_module=unreal)
