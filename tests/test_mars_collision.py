"""Fake trace results exercise acceptance rules, not an installed Unreal engine."""
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from mars_rover.terrain import Dem, prepare_bundle


@pytest.fixture
def collision(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "Content/Python"))
    module = importlib.import_module("mars_collision")
    setup = importlib.import_module("mars_setup")
    y, x = np.mgrid[:5, :5]
    path = prepare_bundle(Dem((0.1 * x + 0.2 * y), 1, (0, 0), {"uri": "test"}), tmp_path / "bundle")
    manifest, heights = setup.load_bundle(path)
    return module, manifest, heights


def trace_engine(landscape, height_offset_cm=0, missed=False, wrong_actor=False):
    engine = MagicMock()
    engine.Vector.side_effect = lambda x, y, z: SimpleNamespace(x=x, y=y, z=z)
    def trace(**kwargs):
        if missed:
            return None
        start, end = kwargs["start"], kwargs["end"]
        point = SimpleNamespace(x=start.x, y=start.y, z=(start.z + end.z) / 2 + height_offset_cm)
        normal = SimpleNamespace(x=0, y=0, z=1)
        fields = [True, False, 0.5, 1, point, point, normal, normal, None,
                  object() if wrong_actor else landscape, None, "None", "None", 0, 0, 0, start, end]
        hit = MagicMock()
        hit.to_tuple.return_value = tuple(fields)
        return hit
    engine.SystemLibrary.line_trace_single.side_effect = trace
    return engine


def test_collision_requires_both_simple_and_complex_traces(collision):
    module, manifest, heights = collision
    landscape = object()
    engine = trace_engine(landscape)
    report = module.verify_landscape(engine, object(), landscape, manifest, heights)
    assert report["verified"] is True
    assert report["trace_count"] >= 18
    assert {call.kwargs["trace_complex"] for call in engine.SystemLibrary.line_trace_single.call_args_list} == {False, True}
    assert all(call.kwargs["ignore_self"] is False for call in engine.SystemLibrary.line_trace_single.call_args_list)


@pytest.mark.parametrize("options", [{"missed": True}, {"wrong_actor": True}, {"height_offset_cm": 5}])
def test_missing_wrong_or_shifted_collision_cannot_pass(collision, options):
    module, manifest, heights = collision
    landscape = object()
    with pytest.raises(RuntimeError, match="collision|Collision"):
        module.verify_landscape(trace_engine(landscape, **options), object(), landscape, manifest, heights)
