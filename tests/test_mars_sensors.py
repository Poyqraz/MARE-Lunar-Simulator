import importlib
import struct

import numpy as np
import pytest


def sensors():
    return importlib.import_module("mars_rover.sensors")


def lidar_packet(points, *, columns=None, frame=7):
    values = [(*p, 20, i // (columns or len(points)), i % (columns or len(points))) for i, p in enumerate(points)]
    payload = b"".join(struct.pack("<ffffHH", *p) for p in values)
    return (
        struct.pack(
            "<4sBBHQdffIIII", b"LIDR", 1, 0, 1, frame, 1700000000.5, 90, 30, columns or len(points), 1, len(points), 20
        )
        + payload
    )


def nav_packet(pixels, *, version=2, frame=7, fmt=2, camera=4):
    pixels = np.asarray(pixels, dtype="<f4" if fmt == 2 else "uint8")
    h, w = pixels.shape[:2]
    header = struct.pack("<4sBBBBHHQI", b"NAVF", version, camera, fmt, 0, w, h, frame, w * h * 4)
    return header + (struct.pack("<Q", 1700000000500000000) if version == 2 else b"") + pixels.tobytes()


def test_lidar_decoder_handles_fragmentation_coalescing_nan_and_epoch_time():
    s = sensors()
    packet = lidar_packet([[1, 2, 3], [np.nan, np.nan, np.nan]])
    stream = s.LidarStream()
    assert stream.feed(packet[:19]) == []
    scans = stream.feed(packet[19:] + packet)
    assert len(scans) == 2
    assert scans[0].stamp_ns == 1700000000500000000
    np.testing.assert_allclose(scans[0].points[0], [1, 2, 3])
    assert np.isnan(scans[0].points[1]).all()


def test_depth_is_planar_cm_not_ray_range_and_invalid_pixels_stay_unknown():
    s = sensors()
    stream = s.NavStream()
    frames = stream.feed(nav_packet([[100, 200], [np.inf, -1]]))
    depth = frames[0].depth_m()
    np.testing.assert_allclose(depth[0], [1, 2])
    assert np.isnan(depth[1]).all()
    points = s.depth_points(np.full((3, 3), 2.0), hfov_deg=90)
    # Off-axis points retain axial Z=2; their ray range is longer than 2.
    np.testing.assert_allclose(points[:, 2], 2)
    assert np.linalg.norm(points[0]) > 2


def test_bad_header_or_oversize_payload_cannot_allocate_arbitrary_memory():
    s = sensors()
    packet = bytearray(lidar_packet([[1, 2, 3]]))
    packet[44:48] = struct.pack("<I", 1000000)
    with pytest.raises(ValueError):
        s.LidarStream().feed(packet)
    packet = bytearray(nav_packet([[1, 2], [3, 4]]))
    packet[20:24] = struct.pack("<I", 2**31)
    with pytest.raises(ValueError):
        s.NavStream().feed(packet)


def test_unstamped_legacy_frames_are_identified_for_playback_only():
    frame = sensors().NavStream().feed(nav_packet([[100]], version=1))[0]
    assert frame.stamp_ns is None


def test_full_unreal_attitude_and_exact_timestamp_are_preserved():
    pose = sensors().pose_from_telemetry(
        dict(x=-100, y=200, z=300, roll=0, pitch=20, yaw=180, t_ns="1700000000500000001")
    )
    assert pose.stamp_ns == 1700000000500000001
    np.testing.assert_allclose(pose.matrix[:3, 3], [1, 2, 3])
    assert pose.matrix[2, 0] > 0.3
    assert np.linalg.det(pose.matrix[:3, :3]) == pytest.approx(1)


def test_pose_history_does_not_use_current_pose_for_an_old_capture():
    s = sensors()
    history = s.PoseHistory()
    for ns, x in [(1000000000, 0), (1200000000, -200)]:
        history.add(s.pose_from_telemetry(dict(x=x, y=0, z=0, roll=0, pitch=0, yaw=180, t_ns=str(ns))))
    pose = history.at(1100000000)
    assert pose.matrix[0, 3] == pytest.approx(1)
    with pytest.raises(ValueError, match="pose|Pose"):
        history.at(1500000000)


def test_bad_organized_indices_and_absurd_epoch_are_rejected():
    s = sensors()
    packet = bytearray(lidar_packet([[1, 2, 3], [1, 2, 3]]))
    packet[48 + 20 + 18 : 48 + 20 + 20] = struct.pack("<H", 0)
    with pytest.raises(ValueError):
        s.LidarStream().feed(packet)
    packet = bytearray(lidar_packet([[1, 2, 3]]))
    packet[16:24] = struct.pack("<d", 1e300)
    with pytest.raises(ValueError):
        s.LidarStream().feed(packet)


def test_stationary_gate_waits_for_a_stable_capture_time_window():
    s = sensors()
    history = s.PoseHistory()
    for ns in range(1000000000, 3000000000, 200000000):
        history.add(s.pose_from_telemetry(dict(x=0, y=0, z=0, roll=0, pitch=0, yaw=180, t_ns=str(ns))))
    assert not history.is_stationary(2)
    history.add(s.pose_from_telemetry(dict(x=0, y=0, z=0, roll=0, pitch=0, yaw=180, t_ns="3000000000")))
    assert history.is_stationary(2)
    history.add(s.pose_from_telemetry(dict(x=0, y=0, z=20, roll=0, pitch=0, yaw=180, t_ns="3100000000")))
    assert not history.is_stationary(2)


def test_stationary_gate_does_not_join_a_long_unobserved_pose_gap():
    s = sensors()
    history = s.PoseHistory()
    for ns in [1000000000, 3000000000]:
        history.add(s.pose_from_telemetry(dict(x=0, y=0, z=0, roll=0, pitch=0, yaw=180, t_ns=str(ns))))
    assert not history.is_stationary(2)


def test_pitched_rover_ground_points_do_not_become_false_negative_obstacles():
    import math
    from mars_rover.planning import TerrainMap, PlanningLimits

    s = sensors()
    pose = s.pose_from_telemetry(dict(x=-500, y=500, z=50, roll=0, pitch=15, yaw=180, t_ns="1700000000000000000"))
    mount = np.eye(4)
    mount[2, 3] = 0.5
    local_z = -0.5 - (0.5 + 2 * math.sin(math.radians(15))) / math.cos(math.radians(15))
    world = s.transform_points(np.array([[2, 0, local_z]]), pose.matrix @ mount)
    assert world[0, 2] == pytest.approx(0, abs=1e-12)
    grid = TerrainMap(np.zeros((20, 20)), 1, PlanningLimits(robot_radius_m=0))
    result = grid.observe(world)
    assert result["positive_obstacles"] == result["negative_obstacles"] == 0


def test_sensor_plugins_use_the_same_clock_implementation():
    from pathlib import Path

    root = Path(__file__).parents[1] / "Plugins"
    paths = list(root.glob("*/Source/*/Private/GncSimTime.h"))
    assert len(paths) == 5
    assert len({p.read_bytes() for p in paths}) == 1
