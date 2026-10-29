"""Import lifecycle with simulated nested editor ticks; no native UE acceptance."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def import_run(tmp_path, monkeypatch):
    path = Path(__file__).parents[1] / "Content/Python/mars_scene.py"
    spec = importlib.util.spec_from_file_location("import_lifecycle_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine, world, landscape, handle = MagicMock(), object(), object(), object()
    expected = [32768, 32769]
    result = {"level": "/Game/Mars/LifecycleQA", "status": "importing", "error": None,
              "heightmap_verified": False, "collision_verified": False,
              "landscape": landscape, "rover": None, "gpu_render_verified": False}
    run = SimpleNamespace(engine=engine, world=world, result=result, pending={},
                          report=tmp_path / "acceptance.json", callback=None,
                          reenter_at=None, reentered=False, heights_ready=True,
                          collision_ready=True, target_exists=False, save_success=True,
                          create_target_during_collision=False, on_unregister=None)

    def nested_tick(stage):
        if run.reenter_at == stage and not run.reentered:
            run.reentered = True
            run.callback(0.01)

    def height_data(actor):
        assert actor is landscape
        nested_tick("height")
        return expected if run.heights_ready else []

    def verify(*args, **kwargs):
        nested_tick("collision")
        if not run.collision_ready:
            raise RuntimeError("Collision cooking pending")
        if run.create_target_during_collision:
            run.target_exists = True
        return {"verified": True, "fixture_only": True}

    def save_map(actual_world, level):
        assert actual_world is world and level == result["level"]
        # Native SaveMap can expose the target before returning to Python.
        run.target_exists = True
        nested_tick("save")
        return run.save_success

    def register(callback):
        run.callback = callback
        return handle

    def unregister(actual_handle):
        assert actual_handle is handle
        if run.on_unregister:
            run.on_unregister()

    engine.get_editor_subsystem.return_value.get_editor_world.return_value = world
    engine.EditorLevelLibrary.get_pie_worlds.return_value = []
    engine.DEMLandscapeLibrary.get_heightmap_data.side_effect = height_data
    engine.EditorAssetLibrary.does_asset_exist.side_effect = lambda level: run.target_exists
    engine.EditorLoadingAndSavingUtils.save_map.side_effect = save_map
    engine.register_slate_post_tick_callback.side_effect = register
    engine.unregister_slate_post_tick_callback.side_effect = unregister
    run.verify = MagicMock(side_effect=verify)
    monkeypatch.setitem(sys.modules, "mars_collision", SimpleNamespace(verify_landscape=run.verify))
    module._save_after_import(engine, world, landscape, expected, result, run.pending,
                              str(run.report), {})
    assert len(run.pending) == 1
    return run


def assert_terminal(run, status, error=None):
    assert run.result["status"] == status
    if error is None:
        assert run.result["error"] is None
    else:
        assert error in run.result["error"]
    report = json.loads(run.report.read_text(encoding="utf-8"))
    assert report == {k: v for k, v in run.result.items() if k not in ("landscape", "rover")}
    assert run.result["heightmap_verified"] is (status == "saved")
    assert run.result["collision_verified"] is (status == "saved")
    assert run.pending == {}
    run.engine.unregister_slate_post_tick_callback.assert_called_once()
    snapshot, payload = run.result.copy(), run.report.read_bytes()
    run.callback(0.01)  # An already queued tick must not mutate a terminal result.
    assert run.result == snapshot and run.report.read_bytes() == payload
    run.engine.unregister_slate_post_tick_callback.assert_called_once()


@pytest.mark.parametrize("stage", ["height", "collision", "save"])
def test_nested_tick_cannot_repeat_validation_save_or_report(import_run, stage):
    run = import_run
    run.reenter_at = stage
    run.callback(0.01)
    assert run.reentered
    assert_terminal(run, "saved")
    run.verify.assert_called_once()
    run.engine.EditorLoadingAndSavingUtils.save_map.assert_called_once()
    run.engine.log_error.assert_not_called()


def test_terminal_status_is_not_exposed_to_exit_observer_before_report(import_run):
    run = import_run

    def observer():
        # The dedicated smoke runner may quit the editor on a terminal status.
        assert run.result["status"] == "importing"
        assert len(run.pending) == 1  # A second build is still blocked during finalization.
        run.callback(0.01)

    run.on_unregister = observer
    run.callback(0.01)
    assert_terminal(run, "saved")


def test_genuine_target_created_during_import_is_still_rejected(import_run):
    run = import_run
    run.create_target_during_collision = True
    run.callback(0.01)
    assert_terminal(run, "failed", "Target appeared during import")
    run.engine.EditorLoadingAndSavingUtils.save_map.assert_not_called()


def test_failed_save_stays_failed_even_if_it_pumps_another_tick(import_run):
    run = import_run
    run.reenter_at, run.save_success = "save", False
    run.callback(0.01)
    assert_terminal(run, "failed", "Could not save Mars map")
    run.engine.EditorLoadingAndSavingUtils.save_map.assert_called_once()


@pytest.mark.parametrize("stage", ["collision", "save"])
@pytest.mark.parametrize("interruption", ["world_change", "play"])
def test_context_changed_inside_editor_call_cannot_receive_acceptance(import_run, stage, interruption):
    run = import_run
    operation = run.verify if stage == "collision" else run.engine.EditorLoadingAndSavingUtils.save_map
    original = operation.side_effect

    def interrupt(*args, **kwargs):
        outcome = original(*args, **kwargs)
        if interruption == "world_change":
            run.engine.get_editor_subsystem.return_value.get_editor_world.return_value = object()
        else:
            run.engine.EditorLevelLibrary.get_pie_worlds.return_value = [object()]
        run.callback(0.01)
        return outcome

    operation.side_effect = interrupt
    run.callback(0.01)
    assert_terminal(run, "failed", "Editor world changed or Play started")
    if stage == "collision":
        run.engine.EditorLoadingAndSavingUtils.save_map.assert_not_called()
    else:
        run.engine.EditorLoadingAndSavingUtils.save_map.assert_called_once()


@pytest.mark.parametrize("waiting_on", ["heights_ready", "collision_ready"])
def test_waiting_import_can_resume_on_a_later_tick(import_run, waiting_on):
    run = import_run
    setattr(run, waiting_on, False)
    run.callback(0.01)
    assert run.result["status"] == "importing"
    assert len(run.pending) == 1 and not run.report.exists()
    run.engine.EditorLoadingAndSavingUtils.save_map.assert_not_called()
    setattr(run, waiting_on, True)
    run.callback(0.01)
    assert_terminal(run, "saved")
    assert "last_collision_error" not in run.result


def test_report_io_failure_cannot_publish_success_or_escape_tick(import_run, monkeypatch):
    run = import_run

    def refuse_write(*args, **kwargs):
        raise OSError("Report storage unavailable")

    monkeypatch.setattr(Path, "write_text", refuse_write)
    run.callback(0.01)
    assert run.result["status"] == "failed"
    assert "Report storage unavailable" in run.result["error"]
    assert run.pending == {}
    run.engine.unregister_slate_post_tick_callback.assert_called_once()
    assert not run.report.exists()
    run.callback(0.01)
    run.engine.unregister_slate_post_tick_callback.assert_called_once()
