"""Unreal Editor orchestration; geometry validation lives in mars_setup."""
import hashlib
import json
import math
from pathlib import Path
import re
import time


def load_scene(path=None):
    path = Path(path) if path else Path(__file__).resolve().parents[2] / "Config/Mars/scene.json"
    scene = json.loads(path.read_text(encoding="utf-8"))
    if scene.get("schema_version") != 1:
        raise ValueError("Unsupported Mars scene preset")
    scalar_keys = ("sun_azimuth_deg", "sun_elevation_deg", "sun_illuminance_lux", "fixed_exposure_ev100",
                   "reference_exposure_ev100", "ground_radius_km_fallback", "atmosphere_height_km",
                   "gas_scale_height_km", "dust_scale_height_km", "dust_optical_depth_880nm",
                   "dust_single_scattering_albedo", "sun_distance_km", "mie_anisotropy", "terrain_roughness")
    color_keys = ("rayleigh_scattering_per_km",
                  "terrain_color_a_linear", "terrain_color_b_linear")
    if not set(scalar_keys + color_keys + ("force_visual_lod0", "dust_spectral_model")) <= set(scene):
        raise ValueError("Mars scene preset is missing required scenario parameters")
    if type(scene["force_visual_lod0"]) is not bool:
        raise ValueError("force_visual_lod0 must be a boolean")
    for key in scalar_keys:
        if type(scene[key]) not in (int, float) or not math.isfinite(scene[key]):
            raise ValueError(f"Non-finite scene value: {key}")
    for key in color_keys:
        if len(scene[key]) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in scene[key]):
            raise ValueError(f"Invalid scene RGB vector: {key}")
    if (not -5 <= scene["sun_elevation_deg"] <= 90 or not 0 <= scene["mie_anisotropy"] < 1 or
            not 0 < scene["terrain_roughness"] <= 1 or scene["gas_scale_height_km"] <= 0 or
            scene["dust_scale_height_km"] <= 0 or not 0 <= scene["dust_optical_depth_880nm"] <= 20 or
            not 0 <= scene["dust_single_scattering_albedo"] <= 1 or
            not 200_000_000 <= scene["sun_distance_km"] <= 255_000_000 or
            not 3300 < scene["ground_radius_km_fallback"] < 3500 or
            not 0 < scene["atmosphere_height_km"] <= 200 or scene["sun_illuminance_lux"] <= 0):
        raise ValueError("Scene parameter outside its supported physical/rendering range")
    return scene


def atmosphere_parameters(scene):
    """Grey aerosol coefficients for beta(z)=beta(0)*exp(-z/H), in km^-1.

    Integrate to the declared finite atmosphere top, so optical depth stays
    fixed when changing the assumed dust distribution. This is a controllable
    scenario, not a spectral Mars radiative-transfer calibration.
    """
    column_km = scene["dust_scale_height_km"] * -math.expm1(
        -scene["atmosphere_height_km"] / scene["dust_scale_height_km"])
    extinction = scene["dust_optical_depth_880nm"] / column_km
    ssa = scene["dust_single_scattering_albedo"]
    return {"mie_extinction_per_km": extinction, "mie_scattering_per_km": extinction * ssa,
            "mie_absorption_per_km": extinction * (1 - ssa),
            "sun_angular_diameter_deg": math.degrees(2 * math.asin(695700 / scene["sun_distance_km"])),
            "dust_optical_depth_880nm": scene["dust_optical_depth_880nm"],
            "dust_single_scattering_albedo": ssa, "photometry_validated": False,
            "model": scene["dust_spectral_model"]}


def sun_rotation(azimuth_deg, elevation_deg):
    """UE pitch/yaw for rays FROM the sun; local x=east, y=north, UE.x=-x."""
    return -elevation_deg, (azimuth_deg - 90) % 360


def _lighting(unreal, actors, manifest, scene, mode):
    if mode == "simulation":
        parameters = atmosphere_parameters(scene)
        pitch, yaw = sun_rotation(scene["sun_azimuth_deg"], scene["sun_elevation_deg"])
        sun = actors.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 10000),
                                            unreal.Rotator(pitch=pitch, yaw=yaw, roll=0))
        light = sun.get_component_by_class(unreal.DirectionalLightComponent)
        light.set_mobility(unreal.ComponentMobility.MOVABLE)
        light.set_intensity(scene["sun_illuminance_lux"])
        light.set_editor_property("atmosphere_sun_light", True)
        light.set_editor_property("light_source_angle", parameters["sun_angular_diameter_deg"])
        sky_atmosphere = actors.spawn_actor_from_class(unreal.SkyAtmosphere, unreal.Vector(0, 0, 0))
        atmosphere = sky_atmosphere.get_component_by_class(unreal.SkyAtmosphereComponent)
        radius = manifest["source"].get("reprojection", {}).get("reference_semi_major_m")
        scalar_properties = {
            # Local z=0 is the crop's minimum, not reference-sphere zero.
            "bottom_radius": ((radius / 1000 if radius else scene["ground_radius_km_fallback"]) +
                              manifest.get("vertical_datum_offset_m", 0) / 1000),
            "atmosphere_height": scene["atmosphere_height_km"],
            "rayleigh_exponential_distribution": scene["gas_scale_height_km"],
            "mie_exponential_distribution": scene["dust_scale_height_km"],
            "rayleigh_scattering_scale": 1.0, "mie_scattering_scale": 1.0,
            "mie_absorption_scale": 1.0, "mie_anisotropy": scene["mie_anisotropy"],
            "other_absorption_scale": 0.0,  # remove the default Earth ozone layer
        }
        for key, value in scalar_properties.items():
            atmosphere.set_editor_property(key, value)
        atmosphere.set_editor_property("rayleigh_scattering", unreal.LinearColor(*scene["rayleigh_scattering_per_km"], 1))
        for key in ("mie_scattering", "mie_absorption"):
            value = parameters[key + "_per_km"]
            atmosphere.set_editor_property(key, unreal.LinearColor(value, value, value, 1))
        sky = actors.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 10000))
        sky_component = sky.get_component_by_class(unreal.SkyLightComponent)
        sky_component.set_mobility(unreal.ComponentMobility.MOVABLE)
        sky_component.set_editor_property("real_time_capture", True)
        sky_component.recapture_sky()
    # Reference imagery has baked illumination: no dynamic light/atmosphere pass.
    exposure = scene["fixed_exposure_ev100"] if mode == "simulation" else scene["reference_exposure_ev100"]
    volume = actors.spawn_actor_from_class(unreal.PostProcessVolume, unreal.Vector(0, 0, 0))
    volume.set_editor_property("unbound", True)
    settings = volume.get_editor_property("settings")
    for key, value in {"override_auto_exposure_min_brightness": True,
                       "override_auto_exposure_max_brightness": True,
                       "override_auto_exposure_bias": True, "auto_exposure_bias": 0,
                       "auto_exposure_min_brightness": exposure, "auto_exposure_max_brightness": exposure}.items():
        settings.set_editor_property(key, value)
    volume.set_editor_property("settings", settings)


def build_environment(manifest_path, level_path, *, load_bundle, pending, rover_blueprint=None,
                      spawn_cell=None, preview_material=True, material_path=None, mode="simulation",
                      scene_path=None, report_path=None, navigation_config_path=None):
    import unreal

    if pending:
        raise RuntimeError("A Mars import is pending; finish or cancel it before another build")
    if mode not in ("simulation", "orbital_reference"):
        raise ValueError("mode is simulation or orbital_reference")
    if navigation_config_path:
        if mode != "simulation" or not rover_blueprint:
            raise ValueError("Navigation requires simulation mode and a rover_blueprint")
        if Path(navigation_config_path).exists():
            raise FileExistsError("Choose a new navigation_config_path")
    if manifest_path is None:
        manifest_path = Path(unreal.Paths.convert_relative_path_to_full(
            unreal.Paths.project_content_dir())) / "Mars/Jezero/manifest.json"
    manifest_path = Path(manifest_path).resolve()
    manifest, expected = load_bundle(manifest_path)
    scene = load_scene(scene_path)
    if mode == "orbital_reference" and "imagery" not in manifest:
        raise ValueError("This bundle has no registered orbital reference imagery")
    if not re.fullmatch(r"/Game/Mars/[A-Za-z0-9_]+", level_path):
        raise ValueError("Use a new level directly under /Game/Mars/")
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError("Stop Play before creating the Mars level")
    if unreal.EditorAssetLibrary.does_asset_exist(level_path):
        raise FileExistsError(f"Level exists: {level_path}; open it or use a new level name")
    assets_folder = level_path + "_Assets"
    if preview_material and unreal.EditorAssetLibrary.does_directory_exist(assets_folder):
        raise FileExistsError(f"Assets folder exists: {assets_folder}; choose a new level name")
    utils = unreal.EditorLoadingAndSavingUtils
    if utils.get_dirty_map_packages() or utils.get_dirty_content_packages():
        raise RuntimeError("Save or discard pending editor changes before building Mars")
    rover_class = None
    if rover_blueprint:
        rover_class = unreal.EditorAssetLibrary.load_blueprint_class(rover_blueprint)
        if rover_class is None:
            raise RuntimeError("Rover Blueprint missing; run git lfs pull and check rover_blueprint")
    if not hasattr(unreal, "DEMLandscapeLibrary"):
        raise RuntimeError("Enable/build UnrealDEMLandscape before creating the level")
    material = unreal.load_asset(material_path) if material_path else None
    if material_path and material is None:
        raise ValueError(f"Material not found: {material_path}")
    grid, layout = manifest["grid"], manifest["landscape"]
    col, row = spawn_cell or (grid["width"] // 2, grid["height"] // 2)
    if (type(col) is not int or type(row) is not int or
            not 0 < col < grid["width"] - 1 or not 0 < row < grid["height"] - 1):
        raise ValueError("spawn_cell is (column,row), inside the no-go border")
    world = utils.new_blank_map(False)
    if world is None:
        raise RuntimeError("Unreal could not create an empty map")
    settings = world.get_world_settings()
    settings.set_editor_property("global_gravity_set", True)
    settings.set_editor_property("global_gravity_z", -100 * manifest["gravity_m_s2"])
    transform = unreal.Transform(location=layout["location_cm"], rotation=[0, 0, 0], scale=layout["scale"])
    landscape = unreal.DEMLandscapeLibrary.create_landscape(
        transform, section_size=layout["section_size"], sections_per_component=layout["sections_per_component"],
        component_count_x=layout["component_count_x"], component_count_y=layout["component_count_y"],
        heightmap_file=str(manifest_path.parent / "heightmap.r16"))
    if landscape is None:
        raise RuntimeError("DEM import failed; see LogDEMLandscape")
    landscape.set_actor_label("Mars_Jezero_MeasuredTerrain")
    for key, value in {"collision_mip_level": 0, "simple_collision_mip_level": 0,
                       "bake_material_position_offset_into_collision": False}.items():
        landscape.set_editor_property(key, value)
    if scene["force_visual_lod0"]:
        landscape.set_editor_property("max_lod_level", 0)
    if material is None and preview_material:
        from mars_materials import create_material
        material = create_material(unreal, assets_folder, mode, manifest_path, manifest, scene)
    if material is not None:
        landscape.set_editor_property("landscape_material", material)
    landscape.set_editor_property("tags", ["landscape", "mars", "jezero"])
    for component in landscape.get_components_by_class(unreal.LandscapeComponent):
        component.set_editor_property("collision_mip_level", 0)
        component.set_editor_property("simple_collision_mip_level", 0)
        component.set_render_custom_depth(True)
        component.set_custom_depth_stencil_value(5)
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    encoded_z = expected[row * layout["width"] + layout["width"] - 1 - col]
    z_cm = layout["location_cm"][2] + (encoded_z - 32768) * layout["scale"][2] / 128
    r_cm = grid["resolution_m"] * 100
    rover = None
    if rover_class:
        rover = actors.spawn_actor_from_class(rover_class, unreal.Vector(-col * r_cm, row * r_cm, z_cm + 100),
                                              unreal.Rotator(pitch=0, yaw=180, roll=0))
        if rover is None:
            raise RuntimeError("Could not place the reference rover")
        rover.set_actor_label("Mars_Rover_Reference")
        if isinstance(rover, unreal.Pawn):
            rover.set_editor_property("auto_possess_player", unreal.AutoReceiveInput.PLAYER0)
    _lighting(unreal, actors, manifest, scene, mode)
    navigation_config = None
    if navigation_config_path:
        from mars_sensor_setup import configure_and_export
        navigation_config = configure_and_export(unreal, rover, manifest_path, navigation_config_path)
    camera = actors.spawn_actor_from_class(unreal.CameraActor, unreal.Vector(-col * r_cm, row * r_cm, z_cm + 1500))
    camera.set_actor_label("RoverOrbitCamera" if rover else "MarsSurveyCamera")
    camera.set_editor_property("tags", ["RoverOrbitCamera"] if rover else ["MarsSurveyCamera"])
    unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(
        unreal.Vector(-col * r_cm - 1500, row * r_cm - 1500, z_cm + 1500),
        unreal.Rotator(pitch=-30, yaw=45, roll=0))
    result = {"level": level_path, "landscape": landscape, "rover": rover, "status": "importing",
              "error": None, "mode": mode, "heightmap_verified": False, "collision_verified": False,
              "gravity_m_s2": manifest["gravity_m_s2"], "extent_m": grid["extent_m"],
              "editor_script_executed": True, "gpu_render_verified": False, "visual_qa_passed": False,
              "photometry_validated": False, "wheel_scale_obstacles_validated": False,
              "atmosphere_scenario": atmosphere_parameters(scene) if mode == "simulation" else None,
              "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
              "navigation_sensor_config": navigation_config}
    unreal.log_warning("Mars: measured terrain; rendering presets are illustrative. Orbital reference is "
                       "unlit grayscale, not albedo/true colour. Soil and vehicle physics remain unvalidated.")
    _save_after_import(unreal, world, landscape, expected, result, pending, report_path, manifest)
    return result


def _save_after_import(unreal, world, landscape, expected, result, pending, report_path, manifest):
    started = time.monotonic()
    token = object()

    def tick(delta):
        try:
            current = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
            if current != world or unreal.EditorLevelLibrary.get_pie_worlds(False):
                raise RuntimeError("Editor world changed or Play started during import; map NOT saved")
            heights = unreal.DEMLandscapeLibrary.get_heightmap_data(landscape)
            if len(heights) == len(expected) and all(a == b for a, b in zip(heights, expected)):
                from mars_collision import verify_landscape
                try:
                    collision = verify_landscape(unreal, world, landscape, manifest, expected,
                                                  ignored_actors=[result["rover"]] if result["rover"] else [])
                except RuntimeError as error:
                    if time.monotonic() - started <= 60:
                        result["last_collision_error"] = str(error)
                        return  # collision cooking may finish after the heightmap readback
                    raise
                if unreal.EditorAssetLibrary.does_asset_exist(result["level"]):
                    raise FileExistsError("Target appeared during import")
                if not unreal.EditorLoadingAndSavingUtils.save_map(world, result["level"]):
                    raise RuntimeError("Could not save Mars map")
                result.update(status="saved", heightmap_verified=True, collision_verified=True,
                              collision=collision)
                result.pop("last_collision_error", None)
                unreal.log(f"Mars: heightmap and sampled collision verified; level saved: {result['level']}")
            elif time.monotonic() - started > 60:
                raise RuntimeError("Heightmap did not read back within 60 seconds; map NOT saved")
            else:
                return
        except Exception as error:  # Unreal failures must not escape a Slate callback.
            result.update(status="failed", error=str(error))
            unreal.log_error(f"Mars setup: {error}")
        finally:
            if result["status"] != "importing":
                unreal.unregister_slate_post_tick_callback(pending.pop(token))
                if report_path:
                    report = {k: v for k, v in result.items() if k not in ("landscape", "rover")}
                    path = Path(report_path)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    pending[token] = unreal.register_slate_post_tick_callback(tick)
