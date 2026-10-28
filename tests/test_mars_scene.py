import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PATH = Path(__file__).parents[1] / "Content/Python/mars_scene.py"
SPEC = importlib.util.spec_from_file_location("scene_under_test", PATH)
scene_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scene_module)


@pytest.mark.parametrize("azimuth,expected_yaw", [(0, 270), (90, 0), (180, 90), (270, 180)])
def test_sun_azimuth_respects_north_east_and_unreal_axis_mirror(azimuth, expected_yaw):
    assert scene_module.sun_rotation(azimuth, 35) == (-35, expected_yaw)


def test_reference_mode_does_not_add_light_that_relights_baked_shadows():
    engine, actors = MagicMock(), MagicMock()
    scene_module._lighting(engine, actors, {"source": {}}, scene_module.load_scene(), "orbital_reference")
    classes = [call.args[0] for call in actors.spawn_actor_from_class.call_args_list]
    assert classes == [engine.PostProcessVolume]


def test_simulation_uses_mars_radius_and_removes_earth_ozone_layer():
    engine, actors = MagicMock(), MagicMock()
    manifest = {"source": {"reprojection": {"reference_semi_major_m": 3396190}}}
    scene_module._lighting(engine, actors, manifest, scene_module.load_scene(), "simulation")
    component = actors.spawn_actor_from_class.return_value.get_component_by_class.return_value
    component.set_editor_property.assert_any_call("bottom_radius", 3396.19)
    component.set_editor_property.assert_any_call("other_absorption_scale", 0.0)
    component.set_editor_property.assert_any_call("mie_exponential_distribution", 11.0)


def test_invalid_scene_value_fails_before_creating_assets(tmp_path):
    scene = scene_module.load_scene()
    scene["mie_anisotropy"] = 3
    path = tmp_path / "scene.json"
    path.write_text(json.dumps(scene))
    with pytest.raises(ValueError):
        scene_module.load_scene(path)


def test_project_enables_editor_python_and_landscape_import_explicitly():
    project = json.loads((PATH.parents[2] / "Moon_Simulator.uproject").read_text())
    enabled = {p["Name"] for p in project["Plugins"] if p.get("Enabled") is True}
    assert {"PythonScriptPlugin", "EditorScriptingUtilities", "UnrealDEMLandscape"} <= enabled


def test_texture_sample_connects_the_exposed_uv_pin():
    spec = importlib.util.spec_from_file_location("material_under_test", PATH.with_name("mars_materials.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lib = MagicMock()
    lib.get_material_expression_input_names.return_value = ["UVs", "MipValue"]
    source, target = object(), object()
    module.connect_input(lib, source, target, "Coordinates")
    lib.connect_material_expressions.assert_called_once_with(source, "", target, "UVs")
