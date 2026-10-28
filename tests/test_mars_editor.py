"""Editor contract tests use a fake engine; they are not UE runtime validation."""
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import MagicMock

import numpy as np
import pytest

from mars_rover.terrain import Dem, prepare_bundle


@pytest.fixture
def setup_module(monkeypatch):
    path = Path(__file__).parents[1] / "Content/Python/mars_setup.py"
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("mars_setup", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bundle(tmp_path):
    dem = Dem(np.array([[-3., -2, -1], [0, 1, 2], [3, 4, 5]]), 1.0, (0, 0), {"uri": "test"})
    return prepare_bundle(dem, tmp_path / "bundle")


def test_corrupt_heightmap_is_rejected_before_editor_changes(setup_module, bundle):
    (bundle.parent / "heightmap.r16").write_bytes(b'broken')
    with pytest.raises(ValueError, match="hash"):
        setup_module.load_bundle(bundle)


def test_manifest_cannot_escape_its_bundle(setup_module, bundle):
    m = json.loads(bundle.read_text())
    m["files"]["../outside.r16"] = m["files"].pop("heightmap.r16")
    bundle.write_text(json.dumps(m))
    with pytest.raises(ValueError):
        setup_module.load_bundle(bundle)


@pytest.mark.parametrize("field,value", [("row_direction", "south"), ("extent_m", [300, 300])])
def test_inconsistent_map_geometry_is_rejected(setup_module, bundle, field, value):
    m = json.loads(bundle.read_text())
    m["grid"][field] = value
    bundle.write_text(json.dumps(m))
    with pytest.raises(ValueError):
        setup_module.load_bundle(bundle)


@pytest.mark.parametrize("field", ["scale", "location_cm"])
def test_vertical_transform_cannot_disagree_with_actual_heights(setup_module, bundle, field):
    m = json.loads(bundle.read_text())
    m["landscape"][field][2] *= 10
    bundle.write_text(json.dumps(m))
    with pytest.raises(ValueError, match="vertical|height"):
        setup_module.load_bundle(bundle)


def test_unsaved_work_is_not_implicitly_saved_or_discarded(setup_module, bundle, monkeypatch):
    engine = MagicMock()
    engine.EditorLevelLibrary.get_pie_worlds.return_value = []
    engine.EditorAssetLibrary.does_asset_exist.return_value = False
    engine.EditorAssetLibrary.does_directory_exist.return_value = False
    engine.EditorLoadingAndSavingUtils.get_dirty_map_packages.return_value = [object()]
    monkeypatch.setitem(sys.modules, "unreal", engine)
    with pytest.raises(RuntimeError, match="pending"):
        setup_module.build(str(bundle))
    engine.EditorLoadingAndSavingUtils.new_blank_map.assert_not_called()


def test_play_session_blocks_level_creation(setup_module, bundle, monkeypatch):
    engine = MagicMock()
    engine.EditorLevelLibrary.get_pie_worlds.return_value = [object()]
    monkeypatch.setitem(sys.modules, "unreal", engine)
    with pytest.raises(RuntimeError, match="Play"):
        setup_module.build(str(bundle))
    engine.EditorLoadingAndSavingUtils.new_blank_map.assert_not_called()


def test_existing_target_is_not_overwritten(setup_module, bundle, monkeypatch):
    engine = MagicMock()
    engine.EditorLevelLibrary.get_pie_worlds.return_value = []
    engine.EditorAssetLibrary.does_asset_exist.return_value = True
    monkeypatch.setitem(sys.modules, "unreal", engine)
    with pytest.raises(FileExistsError):
        setup_module.build(str(bundle))
    engine.EditorLoadingAndSavingUtils.new_blank_map.assert_not_called()


def test_level_gravity_import_and_delayed_save(setup_module, bundle, monkeypatch):
    engine = MagicMock()
    engine.EditorLevelLibrary.get_pie_worlds.return_value = []
    engine.EditorAssetLibrary.does_asset_exist.return_value = False
    engine.EditorAssetLibrary.does_directory_exist.return_value = False
    engine.EditorLoadingAndSavingUtils.get_dirty_map_packages.return_value = []
    engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = []
    engine.DEMLandscapeLibrary.get_heightmap_data.return_value = []  # not merged yet
    engine.EditorLoadingAndSavingUtils.save_map.return_value = True
    engine.Pawn = type("FakePawn", (), {})
    world = engine.EditorLoadingAndSavingUtils.new_blank_map.return_value
    engine.get_editor_subsystem.return_value.get_editor_world.return_value = world
    monkeypatch.setitem(sys.modules, "unreal", engine)
    result = setup_module.build(str(bundle), preview_material=False, rover_blueprint="/Game/Blueprints/Leo_Raph")
    engine.EditorLoadingAndSavingUtils.save_map.assert_not_called()
    settings = engine.EditorLoadingAndSavingUtils.new_blank_map.return_value.get_world_settings.return_value
    settings.set_editor_property.assert_any_call("global_gravity_set", True)
    settings.set_editor_property.assert_any_call("global_gravity_z", -371.0)
    call = engine.DEMLandscapeLibrary.create_landscape.call_args
    assert call.kwargs["heightmap_file"].endswith("heightmap.r16")
    # Saving a flat or partially imported Landscape is a failure, not success.
    tick = engine.register_slate_post_tick_callback.call_args.args[0]
    tick(0.1)
    engine.EditorLoadingAndSavingUtils.save_map.assert_not_called()
    _, expected = setup_module.load_bundle(bundle)
    engine.DEMLandscapeLibrary.get_heightmap_data.return_value = expected
    tick(0.1)
    engine.EditorLoadingAndSavingUtils.save_map.assert_called_once()
    assert result["level"] == "/Game/Mars/Jezero"


def fake_idle_engine():
    engine = MagicMock()
    engine.EditorLevelLibrary.get_pie_worlds.return_value = []
    engine.EditorAssetLibrary.does_asset_exist.return_value = False
    engine.EditorAssetLibrary.does_directory_exist.return_value = False
    engine.EditorLoadingAndSavingUtils.get_dirty_map_packages.return_value = []
    engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = []
    engine.DEMLandscapeLibrary.get_heightmap_data.return_value = []
    world = engine.EditorLoadingAndSavingUtils.new_blank_map.return_value
    engine.get_editor_subsystem.return_value.get_editor_world.return_value = world
    engine.Pawn = type("FakePawn", (), {})
    return engine


def test_environment_only_does_not_require_any_rover_asset(setup_module, bundle, monkeypatch):
    engine = fake_idle_engine()
    engine.EditorAssetLibrary.load_blueprint_class.return_value = None
    monkeypatch.setitem(sys.modules, "unreal", engine)
    result = setup_module.build(str(bundle), preview_material=False)
    engine.EditorAssetLibrary.load_blueprint_class.assert_not_called()
    assert result["rover"] is None


def test_world_switch_cancels_save_instead_of_saving_a_stale_world(setup_module, bundle, monkeypatch):
    engine = fake_idle_engine()
    monkeypatch.setitem(sys.modules, "unreal", engine)
    result = setup_module.build(str(bundle), preview_material=False)
    tick = engine.register_slate_post_tick_callback.call_args.args[0]
    engine.get_editor_subsystem.return_value.get_editor_world.return_value = object()
    tick(0.1)
    engine.EditorLoadingAndSavingUtils.save_map.assert_not_called()
    assert result["status"] == "failed"
    assert "world" in result["error"].lower()


def test_second_build_is_blocked_while_first_import_is_pending(setup_module, bundle, monkeypatch):
    engine = fake_idle_engine()
    monkeypatch.setitem(sys.modules, "unreal", engine)
    setup_module.build(str(bundle), preview_material=False)
    with pytest.raises(RuntimeError, match="pending"):
        setup_module.build(str(bundle), level_path="/Game/Mars/Other", preview_material=False)
    assert engine.EditorLoadingAndSavingUtils.new_blank_map.call_count == 1
