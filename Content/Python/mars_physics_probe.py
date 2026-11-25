"""Measure the gravity and rover contact actually applied in a running (PIE) Mars test level.

Editor, Play stopped, in a dedicated test level (its name contains 'Lab'):
    import mars_physics_probe as p
    p.place_drop_probe()            # TEST_GravityProbe sphere 60 m above the terrain, saved
Then start Play and, while it runs:
    p.start_recording()             # samples every rendered frame from the PIE world
    p.stop_recording(r"C:/work/MARE-Lunar-Simulator/Saved/Mars/gravity-run.json")

The fit uses only the free-fall part (before the first contact). It measures the engine
gravity the probe experiences; it says nothing about soil, wheel slip or rover dynamics.
"""
import json
import math
from pathlib import Path

LABEL = "TEST_GravityProbe"
_STATE = {}


def fit_free_fall(samples, *, min_samples=8):
    """Least-squares z = a + b t + c t^2 on (t_s, z_m) samples; returns g = -2c."""
    if len(samples) < min_samples:
        raise ValueError("Not enough free-fall samples")
    t0 = samples[0][0]
    rows = [(t - t0, z) for t, z in samples]
    s = [sum(t ** k for t, _ in rows) for k in range(5)]
    v = [sum(z * t ** k for t, z in rows) for k in range(3)]
    m = [[s[0], s[1], s[2]], [s[1], s[2], s[3]], [s[2], s[3], s[4]]]

    def det(a):
        return (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
                + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))

    d = det(m)
    coeffs = []
    for i in range(3):
        mi = [row[:] for row in m]
        for r in range(3):
            mi[r][i] = v[r]
        coeffs.append(det(mi) / d)
    a, b, c = coeffs
    residual = max(abs(z - (a + b * t + c * t * t)) for t, z in rows)
    return {"g_m_s2": -2 * c, "initial_speed_m_s": b, "max_residual_m": residual, "samples": len(rows),
            "duration_s": rows[-1][0]}


def free_fall_part(samples, radius_m):
    """Samples from release while contact is impossible before the next sample.

    A fast probe crosses many centimetres per frame and bounces, so a fixed gap threshold
    misses the contact; stop once the gap is within twice the last frame's travel plus 5 cm.
    """
    out = []
    for i, (t, z, ground) in enumerate(samples):
        travel = abs(z - samples[i - 1][1]) if i else 0.0
        if z - radius_m - ground < 0.05 + 2 * travel:
            break
        out.append((t, z))
    return out


def place_drop_probe(height_m=60.0, offset_xy_m=(0.0, 20.0)):
    import unreal

    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError("Stop Play first")
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if "Lab" not in world.get_outermost().get_name():
        raise ValueError("Use a dedicated test level whose name contains 'Lab'")
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    if any(a.get_actor_label() == LABEL for a in actors.get_all_level_actors()):
        raise RuntimeError("Probe already placed")
    rover = [a for a in actors.get_all_level_actors() if a.get_actor_label() == "Mars_Rover_Reference"][0]
    p = rover.get_actor_location()
    x, y = p.x - offset_xy_m[0] * 100, p.y + offset_xy_m[1] * 100
    hit = unreal.SystemLibrary.line_trace_single(world, unreal.Vector(x, y, 1e6), unreal.Vector(x, y, -1e6),
                                                 unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, True, [],
                                                 unreal.DrawDebugTrace.NONE, True).to_tuple()
    if hit[0] is not True:
        raise RuntimeError("No terrain under the probe")
    mesh = unreal.load_asset("/Engine/BasicShapes/Sphere")
    probe = actors.spawn_actor_from_object(mesh, unreal.Vector(x, y, hit[5].z + height_m * 100),
                                           unreal.Rotator(pitch=0, yaw=0, roll=0))
    probe.set_actor_label(LABEL)
    probe.set_actor_scale3d(unreal.Vector(0.2, 0.2, 0.2))  # 0.2 m sphere: radius 0.1 m
    probe.tags = ["test_probe", "gravity"]
    component = probe.static_mesh_component
    component.set_mobility(unreal.ComponentMobility.MOVABLE)
    component.set_collision_profile_name("PhysicsActor")
    component.set_simulate_physics(True)
    unreal.EditorLoadingAndSavingUtils.save_current_level()
    return {"probe_start_z_cm": hit[5].z + height_m * 100, "ground_z_cm": hit[5].z}


def start_recording():
    import unreal

    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    if world is None:
        raise RuntimeError("Start Play first")
    actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.StaticMeshActor)
    probe = next((a for a in actors if a.get_actor_label() == LABEL), None)
    rover = next((a for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Pawn)), None)
    if probe is None:
        raise RuntimeError("No TEST_GravityProbe in the PIE world")
    loc = probe.get_actor_location()
    ground = unreal.SystemLibrary.line_trace_single(world, unreal.Vector(loc.x, loc.y, loc.z - 15),
                                                    unreal.Vector(loc.x, loc.y, -1e6),
                                                    unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, True, [probe],
                                                    unreal.DrawDebugTrace.NONE, True).to_tuple()[5].z / 100
    settings = world.get_world_settings()
    _STATE.clear()
    _STATE.update(samples=[], rover=[], ground=ground,
                  world_gravity_z_cm_s2=settings.get_editor_property("global_gravity_z"),
                  global_gravity_set=settings.get_editor_property("global_gravity_set"))

    def tick(_dt):
        if not probe or not world:
            return
        t = unreal.GameplayStatics.get_time_seconds(world)
        p = probe.get_actor_location()
        # Ground directly below the probe now: after contact it may roll downhill.
        below = unreal.SystemLibrary.line_trace_single(world, unreal.Vector(p.x, p.y, p.z - 15),
                                                       unreal.Vector(p.x, p.y, -1e6),
                                                       unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, True, [probe],
                                                       unreal.DrawDebugTrace.NONE, True).to_tuple()
        _STATE["samples"].append((t, p.z / 100, below[5].z / 100 if below[0] else ground))
        if rover:
            r = rover.get_actor_location()
            _STATE["rover"].append((t, r.x / 100, r.y / 100, r.z / 100))

    _STATE["handle"] = unreal.register_slate_post_tick_callback(tick)
    return {"recording": True, "ground_m": ground}


def stop_recording(output=None):
    import unreal

    if "handle" in _STATE:
        unreal.unregister_slate_post_tick_callback(_STATE.pop("handle"))
    samples = _STATE.get("samples", [])
    unique = []
    for s in samples:  # PIE time only advances on world ticks; drop repeated slate frames
        if not unique or s[0] > unique[-1][0]:
            unique.append(s)
    fall = free_fall_part(unique, 0.1)
    result = {"world_settings": {"global_gravity_set": _STATE.get("global_gravity_set"),
                                 "global_gravity_z_cm_s2": _STATE.get("world_gravity_z_cm_s2")},
              "free_fall_fit": fit_free_fall(fall) if len(fall) >= 8 else None,
              "sample_count": len(unique), "rover_track": _STATE.get("rover", [])[-200:],
              "probe_samples": unique,
              "interpretation": "Engine gravity on a free rigid sphere; soil and rover dynamics not validated."}
    if output:
        path = Path(output)
        if path.exists():
            raise FileExistsError(f"{path} exists")
        path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return {k: v for k, v in result.items() if k not in ("probe_samples", "rover_track")}


def _self_check():
    g = 3.71
    pts = [(0.1 + i / 30, 10 - 0.5 * g * (i / 30) ** 2) for i in range(40)]
    assert math.isclose(fit_free_fall(pts)["g_m_s2"], g, rel_tol=1e-9)


_self_check()
