"""Measure the placed reference rover's sensor geometry before Play, stdlib only.

Called by mars_setup.build(navigation_config_path=...). No guessed mount,
baseline, camera id or FOV is used. This is not a native sensor acceptance test.
"""

import hashlib
import json
import math
from pathlib import Path


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def map_frame(component, *, optical=False):
    f, u, p = component.get_forward_vector(), component.get_up_vector(), component.get_world_location()
    name = component.get_name() if hasattr(component, "get_name") else type(component).__name__
    f_world, u_world, p_world = [f.x, f.y, f.z], [u.x, u.y, u.z], [p.x, p.y, p.z]
    if any(not math.isfinite(v) for v in (*f_world, *u_world, *p_world)):
        raise ValueError(f"Sensor transform contains non-finite values (component={name})")
    forward, up = [-f.x, f.y, f.z], [-u.x, u.y, u.z]
    left = _cross(up, forward)
    axes = [[-v for v in left], [-v for v in up], forward] if optical else [forward, left, up]
    if (any(not math.isclose(_dot(a, a), 1, rel_tol=0, abs_tol=1e-5) for a in axes) or
            any(abs(_dot(axes[i], axes[j])) > 1e-5 for i in range(3) for j in range(i))):
        raise ValueError(f"Sensor axes are not an orthonormal rigid basis (component={name}, "
                         f"forward={f_world}, up={u_world}, forward_dot_up={_dot(forward, up)})")
    return [[axes[0][i], axes[1][i], axes[2][i], [-p.x / 100, p.y / 100, p.z / 100][i]] for i in range(3)] + [
        [0, 0, 0, 1]
    ]


def relative_frame(body, sensor):
    # inverse rigid body transform times the sensor transform
    columns = [[body[i][j] for i in range(3)] for j in range(3)]
    result = []
    delta = [sensor[i][3] - body[i][3] for i in range(3)]
    for axis in columns:
        result.append([_dot(axis, [sensor[i][j] for i in range(3)]) for j in range(3)] + [_dot(axis, delta)])
    return result + [[0, 0, 0, 1]]


def parallel_baseline(left, right):
    rel = relative_frame(left, right)
    if (
        any(abs(rel[i][j] - (1 if i == j else 0)) > 1e-5 for i in range(3) for j in range(3))
        or abs(rel[1][3]) > 0.001
        or abs(rel[2][3]) > 0.001
        or not 0 < rel[0][3] < 10
    ):
        raise ValueError("Stereo eyes are not parallel with a positive horizontal baseline; rectification required")
    return rel[0][3]


def configure_and_export(unreal, rover, manifest_path, output):
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError("Stop Play before changing or exporting sensor configuration")
    if rover is None:
        raise ValueError("Navigation requires a reference rover")
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError("Choose a new navigation sensor-config file")
    components = rover.get_components_by_class(unreal.SceneComponent)

    def find(name):
        key = str(name).lower().replace("_", "")
        matches = [c for c in components if c.get_name().lower().replace("_", "") == key]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one rover component named {name}")
        return matches[0]

    base = find("base_link")
    body = map_frame(base)
    lidars = rover.get_components_by_class(unreal.UnrealLidarCam)
    streamers = rover.get_components_by_class(unreal.UnrealStereoCam)
    if len(lidars) != 1:
        raise ValueError("Select a reference rover with exactly one LiDAR for this adapter")
    candidates = []
    for candidate in streamers:
        name = str(candidate.get_editor_property("left_capture_name"))
        if name.lower() not in ("none", ""):
            candidates.append(candidate)
    if len(candidates) != 1:
        raise ValueError("Expected one main stereo streamer with both eyes")
    lidar, streamer = lidars[0], candidates[0]
    left, right, center = [find(streamer.get_editor_property(k + "_capture_name")) for k in ("left", "right", "center")]
    cameras = [left, right, center]
    for camera in cameras:
        if camera.get_editor_property("projection_type") != unreal.CameraProjectionMode.PERSPECTIVE:
            raise ValueError("Only a perspective pinhole camera is supported")

    def size(camera):
        texture = camera.get_editor_property("texture_target")
        return (
            [texture.get_editor_property("size_x"), texture.get_editor_property("size_y")]
            if texture
            else [streamer.get_editor_property("capture_width"), streamer.get_editor_property("capture_height")]
        )

    shapes = [size(c) for c in cameras]
    fovs = [float(c.get_editor_property("fov_angle")) for c in cameras]
    if shapes[0] != shapes[1] or abs(fovs[0] - fovs[1]) > 1e-5:
        raise ValueError("Stereo eyes must have matching dimensions and horizontal FOV")
    left_frame, right_frame = map_frame(left, optical=True), map_frame(right, optical=True)
    baseline = parallel_baseline(left_frame, right_frame)
    follow = str(lidar.get_editor_property("follow_component_name"))
    mount = lidar if follow.lower() in ("none", "") else find(follow)
    # Resolve and validate all mounts before changing component settings.
    report = {
        "schema_version": 1,
        "source": "unreal_editor_components",
        "rover": rover.get_name(),
        "manifest_sha256": hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest(),
        "pose_source": "base_link world telemetry, exact t_ns on shared GncSimTime",
        "lidar": {
            "sensor_id": int(lidar.get_editor_property("sensor_id")),
            "to_body": relative_frame(body, map_frame(mount)),
            "port": 3007,
            "mode": str(lidar.get_editor_property("mode")),
        },
        "depth": {
            "camera_id": int(streamer.get_editor_property("depth_cam_id")),
            "to_body": relative_frame(body, map_frame(center, optical=True)),
            "hfov_deg": fovs[2],
            "width": shapes[2][0],
            "height": shapes[2][1],
            "port": 3004,
            "source": "Unreal central ground-truth planar depth",
        },
        "stereo": {
            "left_id": int(streamer.get_editor_property("left_cam_id")),
            "right_id": int(streamer.get_editor_property("right_cam_id")),
            "to_body": relative_frame(body, left_frame),
            "hfov_deg": fovs[0],
            "width": shapes[0][0],
            "height": shapes[0][1],
            "baseline_m": baseline,
            "rectified_parallel": True,
            "disparity_uncertainty_px_scenario": 1.0,
        },
        "native_sensor_stream_verified": False,
        "native_rover_motion_verified": False,
    }
    # Mutate only this new level's placed rover, with Play stopped.
    for component, values in [
        (
            streamer,
            {
                "server_ip": "127.0.0.1",
                "server_port": 3004,
                "send_hz": 5.0,
                "stream_center_depth": True,
                "limit_auto_exposure": True,
                "lock_exposure": False,
                "min_ev100": 13.0,
                "max_ev100": 13.0,
            },
        ),
        (lidar, {"server_ip": "127.0.0.1", "server_port": 3007, "scan_rate_hz": 10.0}),
    ]:
        for key, value in values.items():
            component.set_editor_property(key, value)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write("\n")
    return str(output)
