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


def test_atmosphere_ground_radius_accounts_for_removed_height_datum():
    engine, actors = MagicMock(), MagicMock()
    manifest = {"source": {"reprojection": {"reference_semi_major_m": 3396190}},
                "vertical_datum_offset_m": -2580.5820169885833}
    scene_module._lighting(engine, actors, manifest, scene_module.load_scene(), "simulation")
    component = actors.spawn_actor_from_class.return_value.get_component_by_class.return_value
    component.set_editor_property.assert_any_call("bottom_radius", pytest.approx(3393.6094179830114))
    component.set_editor_property.assert_any_call("source_angle", pytest.approx(0.3497230666))


def test_invalid_scene_value_fails_before_creating_assets(tmp_path):
    scene = scene_module.load_scene()
    scene["mie_anisotropy"] = 3
    path = tmp_path / "scene.json"
    path.write_text(json.dumps(scene))
    with pytest.raises(ValueError):
        scene_module.load_scene(path)


def test_dust_coefficients_reproduce_declared_optical_depth():
    scene = scene_module.load_scene()
    values = scene_module.atmosphere_parameters(scene)
    import math
    column = scene["dust_scale_height_km"] * -math.expm1(-scene["atmosphere_height_km"] / scene["dust_scale_height_km"])
    assert (values["mie_scattering_per_km"] + values["mie_absorption_per_km"]) * column == pytest.approx(0.45)
    assert values["mie_scattering_per_km"] / values["mie_extinction_per_km"] == pytest.approx(0.93)
    assert values["sun_angular_diameter_deg"] == pytest.approx(0.3497, abs=0.001)
    assert values["photometry_validated"] is False


@pytest.mark.parametrize("key,value", [("dust_optical_depth_880nm", -1),
                                      ("dust_single_scattering_albedo", 1.1),
                                      ("dust_scale_height_km", 0), ("sun_distance_km", float("nan"))])
def test_nonphysical_atmosphere_scenarios_are_rejected(tmp_path, key, value):
    scene = scene_module.load_scene()
    scene[key] = value
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


@pytest.mark.parametrize("position_pin", ["World Position", "Position"])
def test_procedural_graph_connects_world_position_to_the_exposed_noise_pin(position_pin):
    """The first pin list is from the user's failed UE 5.7.4 native import."""
    spec = importlib.util.spec_from_file_location("material_under_test", PATH.with_name("mars_materials.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = MagicMock()
    engine.EditorAssetLibrary.does_asset_exist.return_value = False
    engine.EditorAssetLibrary.save_asset.return_value = True
    lib = engine.MaterialEditingLibrary
    expressions = {}

    def create_expression(material, expression_class):
        expression = MagicMock()
        expressions[expression_class] = expression
        return expression

    lib.create_material_expression.side_effect = create_expression
    lib.get_material_expression_input_names.side_effect = lambda target: (
        [position_pin, "FilterWidth"]
        if target is expressions[engine.MaterialExpressionNoise] else ["A", "B", "Alpha"])
    lib.connect_material_expressions.return_value = True
    lib.connect_material_property.return_value = True
    module.create_material(engine, "/Game/Mars/Test_Assets", "simulation", None, {}, scene_module.load_scene())
    lib.connect_material_expressions.assert_any_call(
        expressions[engine.MaterialExpressionWorldPosition], "",
        expressions[engine.MaterialExpressionNoise], position_pin)


def test_noise_position_cannot_fall_back_to_filter_width():
    spec = importlib.util.spec_from_file_location("material_under_test", PATH.with_name("mars_materials.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lib = MagicMock()
    lib.get_material_expression_input_names.return_value = ["FilterWidth"]
    with pytest.raises(RuntimeError, match="Material input not exposed"):
        module.connect_input(lib, object(), object(), "Position")
    lib.connect_material_expressions.assert_not_called()


def test_material_connection_rejected_by_unreal_is_not_silenced():
    spec = importlib.util.spec_from_file_location("material_under_test", PATH.with_name("mars_materials.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lib = MagicMock()
    lib.get_material_expression_input_names.return_value = ["World Position", "FilterWidth"]
    lib.connect_material_expressions.return_value = False
    with pytest.raises(RuntimeError, match="Cannot connect material input World Position"):
        module.connect_input(lib, object(), object(), "Position")
