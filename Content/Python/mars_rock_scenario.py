"""Place a SYNTHETIC rock scenario (mars_rover.rock_scenario JSON) into a new Mars test level.

In Unreal's Python console, with Play stopped and the target lab level open:
    import mars_rock_scenario
    mars_rock_scenario.place(r"C:/work/MARE-Lunar-Simulator/Saved/Mars/belva-rocks-01.json")

Rocks are procedural ellipsoids for pipeline tests, labelled SYNTH_Rock_* and tagged
synthetic_rock; they are not measured Mars objects. Collision uses the mesh triangles
(complex as simple) so non-uniform scale stays exact for wheels, traces and CPU LiDAR.
"""
import hashlib
import json
import math
from pathlib import Path

TAG = "synthetic_rock"


def ue_location(x_m, y_m, z_m):
    """Local ROS metres (x east, y north) to Unreal cm with MARE's UE.x = -ROS.x."""
    return -x_m * 100.0, y_m * 100.0, z_m * 100.0


def center_height_m(ground_m, rock):
    """Ellipsoid centre so exactly exposed_height_m stands above the ground point."""
    return ground_m + rock["exposed_height_m"] - rock["size_m"][2] / 2


def _rock_mesh(unreal, folder):
    path = folder + "/SynthRock_Ellipsoid"
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        return unreal.load_asset(path)
    mesh = unreal.EditorAssetLibrary.duplicate_asset("/Engine/BasicShapes/Sphere", path)
    if mesh is None:
        raise RuntimeError("Could not create the synthetic rock mesh")
    body = mesh.get_editor_property("body_setup")
    body.set_editor_property("collision_trace_flag", unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE)
    unreal.EditorAssetLibrary.save_loaded_asset(mesh)
    return mesh


def place(scenario_path, *, save=True):
    import unreal

    path = Path(scenario_path)
    scenario = json.loads(path.read_text(encoding="utf-8"))
    if scenario.get("kind") != "synthetic_rock_test" or scenario.get("schema_version") != 1:
        raise ValueError("Expected a schema 1 synthetic_rock_test scenario")
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError("Stop Play before placing rocks")
    editor = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    world = editor.get_editor_world()
    level = world.get_outermost().get_name()
    if not level.startswith("/Game/Mars/") or "Rock" not in level:
        raise ValueError(f"Open a dedicated rock test level (name containing 'Rock'), not {level}")
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    existing = [a for a in actors.get_all_level_actors() if TAG in [str(t) for t in a.tags]]
    if existing:
        raise RuntimeError("This level already holds synthetic rocks; use a new level")
    terrain = [a for a in actors.get_all_level_actors() if a.get_actor_label() == "Mars_Jezero_MeasuredTerrain"]
    if len(terrain) != 1:
        raise RuntimeError("Expected exactly one measured terrain Landscape")
    ignore = [a for a in actors.get_all_level_actors() if a.get_actor_label() == "Mars_Rover_Reference"]
    mesh = _rock_mesh(unreal, level + "_Assets")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    placed = []
    for rock in scenario["rocks"]:
        x, y, _ = ue_location(*rock["center_xy_m"], 0)
        hit = unreal.SystemLibrary.line_trace_single(
            world, unreal.Vector(x, y, 1e6), unreal.Vector(x, y, -1e6), unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
            True, ignore, unreal.DrawDebugTrace.NONE, True).to_tuple()
        if hit[0] is not True or hit[9] != terrain[0]:
            raise RuntimeError(f"No terrain under {rock['id']}")
        ground_m = hit[5].z / 100
        location = unreal.Vector(x, y, center_height_m(ground_m, rock) * 100)
        # Mirrored x axis: a ROS yaw (counter-clockwise from east) becomes 180 - yaw in Unreal.
        # Keywords: unreal.Rotator's positional order is (roll, pitch, yaw).
        rotation = unreal.Rotator(pitch=0, yaw=180 - rock["yaw_deg"], roll=0)
        actor = actors.spawn_actor_from_object(mesh, location, rotation)
        actor.set_actor_label("SYNTH_Rock_" + rock["id"])
        actor.set_actor_scale3d(unreal.Vector(*rock["size_m"]))  # engine sphere is 1 m across
        actor.tags = [TAG, rock["class"], "scenario_sha256:" + digest[:16]]
        component = actor.static_mesh_component
        component.set_mobility(unreal.ComponentMobility.STATIC)
        component.set_collision_profile_name("BlockAll")
        # Measure the placed collision: a vertical trace must hit this rock at its designed top.
        tops = []
        for complex_trace in (False, True):
            top = unreal.SystemLibrary.line_trace_single(
                world, unreal.Vector(x, y, location.z + 1000), unreal.Vector(x, y, location.z - 1000),
                unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, complex_trace, [], unreal.DrawDebugTrace.NONE, True).to_tuple()
            if top[0] is not True or top[9] != actor:
                raise RuntimeError(f"Collision trace missed synthetic rock {rock['id']}")
            tops.append(top[5].z / 100 - ground_m)
        placed.append({"id": rock["id"], "ground_z_cm": hit[5].z, "center_cm": [location.x, location.y, location.z],
                       "traced_top_above_ground_m": [round(t, 4) for t in tops]})
        # Faceted engine sphere: its pole vertex is exact; 5 mm covers float and trace error.
        if any(not math.isclose(t, rock["exposed_height_m"], abs_tol=0.005) for t in tops):
            raise RuntimeError(f"Traced top of {rock['id']} {tops} m differs from {rock['exposed_height_m']} m")
    if save:
        unreal.EditorLoadingAndSavingUtils.save_current_level()
    return {"level": level, "scenario_sha256": digest, "rocks": placed, "measured_mars_objects": False}
