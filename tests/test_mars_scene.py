import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, call

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
    component.set_editor_property.assert_any_call("light_source_angle", pytest.approx(0.3497230666))


@pytest.mark.parametrize("mode", ["simulation", "orbital_reference"])
def test_lighting_uses_documented_ue57_editor_properties(mode):
    """Reject unknown names, as native set_editor_property does (not MagicMock)."""
    # Independent UE 5.7 API allowlists; references are in the native test runbook.
    properties = {
        "DirectionalLightComponent": {"atmosphere_sun_light", "light_source_angle"},
        "SkyAtmosphereComponent": {
            "bottom_radius", "atmosphere_height", "rayleigh_exponential_distribution",
            "mie_exponential_distribution", "rayleigh_scattering_scale", "mie_scattering_scale",
            "mie_absorption_scale", "mie_anisotropy", "other_absorption_scale",
            "rayleigh_scattering", "mie_scattering", "mie_absorption",
        },
        "SkyLightComponent": {"real_time_capture"},
        "PostProcessVolume": {"unbound", "settings"},
        "PostProcessSettings": {
            "override_auto_exposure_min_brightness", "override_auto_exposure_max_brightness",
            "override_auto_exposure_bias", "auto_exposure_bias",
            "auto_exposure_min_brightness", "auto_exposure_max_brightness",
        },
    }
    values = {name: {} for name in properties}

    def editor_object(name):
        obj = MagicMock(name=name)

        def set_property(key, value):
            if key not in properties[name]:
                raise AttributeError(f"{name}: unknown UE 5.7 editor property {key}")
            values[name][key] = value

        obj.set_editor_property.side_effect = set_property
        return obj

    engine, actors = MagicMock(), MagicMock()
    components = {name: editor_object(name) for name in properties}
    volume = components["PostProcessVolume"]
    volume.get_editor_property.return_value = components["PostProcessSettings"]
    actor_map = {engine.PostProcessVolume: volume}
    for actor_name, component_name in (("DirectionalLight", "DirectionalLightComponent"),
                                       ("SkyAtmosphere", "SkyAtmosphereComponent"),
                                       ("SkyLight", "SkyLightComponent")):
        actor = MagicMock(name=actor_name)
        actor.get_component_by_class.side_effect = {getattr(engine, component_name): components[component_name]}.__getitem__
        actor_map[getattr(engine, actor_name)] = actor
    actors.spawn_actor_from_class.side_effect = lambda cls, *args, **kwargs: actor_map[cls]
    scene = scene_module.load_scene()
    scene_module._lighting(engine, actors, {"source": {}}, scene, mode)
    if mode == "simulation":
        assert values["DirectionalLightComponent"]["light_source_angle"] == pytest.approx(0.3497, abs=0.001)
        assert values["SkyAtmosphereComponent"]["other_absorption_scale"] == 0
    else:
        assert values["DirectionalLightComponent"] == {}
        assert values["SkyAtmosphereComponent"] == {}
        assert values["SkyLightComponent"] == {}
    exposure = scene["fixed_exposure_ev100"] if mode == "simulation" else scene["reference_exposure_ev100"]
    assert values["PostProcessSettings"]["auto_exposure_min_brightness"] == exposure
    assert values["PostProcessSettings"]["auto_exposure_max_brightness"] == exposure


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


@pytest.mark.parametrize("reported_name", ["None", ""])
def test_single_unnamed_input_uses_documented_first_input_selector(reported_name):
    """UE 5.7.4 reported ['None'] for the reference graph's ComponentMask."""
    spec = importlib.util.spec_from_file_location("material_under_test", PATH.with_name("mars_materials.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lib = MagicMock()
    lib.get_material_expression_input_names.return_value = [reported_name]
    lib.connect_material_expressions.return_value = True
    source, target = object(), object()
    module.connect_input(lib, source, target, "Input")
    lib.connect_material_expressions.assert_called_once_with(source, "", target, "")


@pytest.mark.parametrize("pins", [["None", "FilterWidth"], ["", "FilterWidth"], ["FilterWidth"]])
def test_unnamed_input_is_not_selected_when_other_inputs_make_it_ambiguous(pins):
    spec = importlib.util.spec_from_file_location("material_under_test", PATH.with_name("mars_materials.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lib = MagicMock()
    lib.get_material_expression_input_names.return_value = pins
    with pytest.raises(RuntimeError, match="Material input not exposed"):
        module.connect_input(lib, object(), object(), "Input")
    lib.connect_material_expressions.assert_not_called()


def test_rejected_unnamed_input_connection_remains_a_failure():
    spec = importlib.util.spec_from_file_location("material_under_test", PATH.with_name("mars_materials.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lib = MagicMock()
    lib.get_material_expression_input_names.return_value = ["None"]
    lib.connect_material_expressions.return_value = False
    with pytest.raises(RuntimeError, match="Cannot connect material input"):
        module.connect_input(lib, object(), object(), "Input")
    assert lib.connect_material_expressions.call_args.args[-1] == ""


def test_orbital_material_connects_both_single_unnamed_masks_and_uvs(tmp_path):
    """Exercise the whole orbital graph; only mask pin names are native observations."""
    spec = importlib.util.spec_from_file_location("material_under_test", PATH.with_name("mars_materials.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = MagicMock()
    engine.EditorAssetLibrary.does_asset_exist.return_value = False
    engine.EditorAssetLibrary.save_asset.return_value = True
    texture_path = "/Game/Mars/Test_Assets/T_JezeroOrbitalReference"
    engine.AssetImportTask.return_value.get_editor_property.return_value = [texture_path]
    lib = engine.MaterialEditingLibrary
    lib.connect_material_expressions.return_value = True
    lib.connect_material_property.return_value = True
    expressions, input_names = {}, {}
    pins = {engine.MaterialExpressionWorldPosition: [], engine.MaterialExpressionComponentMask: ["None"],
            engine.MaterialExpressionMultiply: ["A", "B"], engine.MaterialExpressionAdd: ["A", "B"],
            engine.MaterialExpressionAppendVector: ["A", "B"],
            engine.MaterialExpressionTextureSampleParameter2D: ["UVs", "MipValue"]}

    def create_expression(material, expression_class):
        expression = MagicMock()
        expressions.setdefault(expression_class, []).append(expression)
        input_names[expression] = pins[expression_class]
        return expression

    lib.create_material_expression.side_effect = create_expression
    lib.get_material_expression_input_names.side_effect = lambda expression: input_names[expression]
    manifest = {"imagery": {"filename": "ortho_reference.png"}, "grid": {"extent_m": [252, 252]}}
    module.create_material(engine, "/Game/Mars/Test_Assets", "orbital_reference",
                           tmp_path / "manifest.json", manifest, {})
    position = expressions[engine.MaterialExpressionWorldPosition][0]
    mask_x, mask_y = expressions[engine.MaterialExpressionComponentMask]
    scale_x, scale_y = expressions[engine.MaterialExpressionMultiply]
    offset_y = expressions[engine.MaterialExpressionAdd][0]
    uv = expressions[engine.MaterialExpressionAppendVector][0]
    sample = expressions[engine.MaterialExpressionTextureSampleParameter2D][0]
    assert lib.connect_material_expressions.call_args_list == [
        call(position, "", mask_x, ""), call(position, "", mask_y, ""),
        call(mask_x, "", scale_x, "A"), call(mask_y, "", scale_y, "A"),
        call(scale_y, "", offset_y, "A"), call(scale_x, "", uv, "A"),
        call(offset_y, "", uv, "B"), call(uv, "", sample, "UVs"),
    ]
    # UE.x points west and UE.y north; these values map the survey image north-up.
    mask_x.set_editor_property.assert_any_call("r", True)
    mask_y.set_editor_property.assert_any_call("g", True)
    scale_x.set_editor_property.assert_any_call("const_b", -1 / 25200)
    scale_y.set_editor_property.assert_any_call("const_b", -1 / 25200)
    offset_y.set_editor_property.assert_any_call("const_b", 1.0)
    sample.set_editor_property.assert_any_call("texture", engine.load_asset.return_value)
    engine.AssetToolsHelpers.get_asset_tools.return_value.create_asset.return_value.set_editor_property.assert_any_call(
        "shading_model", engine.MaterialShadingModel.MSM_UNLIT)
    lib.connect_material_property.assert_called_once_with(sample, "", engine.MaterialProperty.MP_EMISSIVE_COLOR)
    engine.EditorAssetLibrary.save_asset.assert_any_call(texture_path)
    engine.EditorAssetLibrary.save_asset.assert_any_call("/Game/Mars/Test_Assets/M_JezeroOrbitalReference")


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
