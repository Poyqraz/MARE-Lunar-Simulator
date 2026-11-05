import math
import struct

import numpy as np
import pytest

from mars_rover.navigation import NavigationSession
from mars_rover.planning import PlanningLimits, TerrainMap
from mars_rover.sensors import LidarScan, LidarStream, pose_from_telemetry


def packet_v2(pose, points=((1.0, 0.0, 0.0),)):
    points = list(points)
    header = struct.pack("<4sBBHQdffIIII", b"LIDR", 2, 0, 3, 1, 1700000000.0, 90, 30,
                         len(points), 1, len(points), 20)
    extension = struct.pack("<12d", *np.asarray(pose)[:3, :].ravel())
    payload = b"".join(struct.pack("<ffffHH", *point, 20, 0, i) for i, point in enumerate(points))
    return header + extension + payload


def test_cpu_packet_is_fragmented_and_keeps_point_and_transform_together():
    matrix = np.eye(4)
    matrix[:3, 3] = (12, 13, 4)
    first = packet_v2(matrix, [(2, -1, 3), (3, 2, 1)])
    second = packet_v2(np.eye(4))
    stream = LidarStream()
    assert stream.feed(first[:75]) == []
    frames = stream.feed(first[75:] + second)
    assert len(frames) == 2
    np.testing.assert_allclose(frames[0].cpu_capture_to_world, matrix)
    np.testing.assert_allclose(frames[0].points, [[2, -1, 3], [3, 2, 1]])
    np.testing.assert_allclose(frames[1].cpu_capture_to_world, np.eye(4))


@pytest.mark.parametrize("corrupt", ["scale", "reflection", "nan", "wrong_flag"])
def test_cpu_packet_rejects_invalid_pose_or_incorrect_flags(corrupt):
    matrix = np.eye(4)
    if corrupt == "scale":
        matrix[0, 0] = 2
    elif corrupt == "reflection":
        matrix[0, 0] = -1
    elif corrupt == "nan":
        matrix[0, 3] = np.nan
    data = bytearray(packet_v2(matrix))
    if corrupt == "wrong_flag":
        data[6:8] = struct.pack("<H", 1)
    with pytest.raises(ValueError):
        LidarStream().feed(data)


def scenario(mode):
    grid = TerrainMap(np.zeros((24, 24)), 1, PlanningLimits(robot_radius_m=0))
    config = {"schema_version": 1, "manifest_sha256": None,
              "lidar": {"sensor_id": 0, "to_body": np.eye(4).tolist()},
              "depth": {"camera_id": 4, "hfov_deg": 90, "to_body": np.eye(4).tolist()}}
    session = NavigationSession(grid, config, min_points=1, settle_s=0,
                                obstacle_diagnostics=True, lidar_pose_source=mode)
    telemetry = {"x": -1000, "y": 1000, "z": 100, "roll": 0, "pitch": 0, "yaw": 180,
                 "t_ns": "1700000000000000000"}
    status = {"connected": True, "connection_id": 1, "telemetry_age_s": 0,
              "telemetry_unreal": telemetry}
    body = pose_from_telemetry(telemetry).matrix
    a = math.radians(3)
    rotation = np.array([[math.cos(a), 0, math.sin(a), 0], [0, 1, 0, 0],
                         [-math.sin(a), 0, math.cos(a), 0], [0, 0, 0, 1]])
    capture = body @ rotation
    # A ground return and two real height differences, all inside the map.
    world = np.array([[16, 10, 0], [14, 9, 0.30], [14, 11, -0.30]])
    local = (world - capture[:3, 3]) @ capture[:3, :3]
    session.step(status, now=1)
    return session, status, capture, local


def test_actual_cpu_capture_pose_removes_artificial_ground_tilt_but_preserves_hazards():
    session, status, capture, local = scenario("cpu_capture")
    scan = LidarStream().feed(packet_v2(capture, local))[0]
    session.feed_lidar(scan, now=1)
    session.step(status, now=1.01)
    assert not session.grid.raw_blocked[10, 16]
    assert session.grid.raw_blocked[9, 14]
    assert session.grid.raw_blocked[11, 14]
    assert session.health["lidar"]["pose_source"] == "cpu_capture"
    diagnostic = session._obstacle_frames[-1]
    assert diagnostic["pose_source"] == "cpu_capture"
    np.testing.assert_allclose(diagnostic["world_from_sensor_used"], capture)

    # The same rays projected with the old body pose misclassify the ground.
    old, status, _, local = scenario("telemetry")
    old.feed_lidar(LidarScan(0, 1, 1700000000000000000, local, 1, 3), now=1)
    old.step(status, now=1.01)
    assert old.grid.raw_blocked[10, 16]


def test_mode_mismatch_discards_previous_lidar_health_and_never_falls_back():
    session, status, capture, local = scenario("cpu_capture")
    session.feed_lidar(LidarScan(0, 1, 1700000000000000000, local, 1, 3, capture), now=1)
    session.step(status, now=1.01)
    assert "lidar" in session.health
    with pytest.raises(ValueError, match="pose source"):
        session.feed_lidar(LidarScan(0, 2, 1700000000000000000, local, 1, 3), now=1.02)
    assert "lidar" not in session.health
    assert "lidar" not in session.latest

    legacy, _, capture, local = scenario("telemetry")
    with pytest.raises(ValueError, match="pose source"):
        legacy.feed_lidar(LidarScan(0, 2, 1700000000000000000, local, 1, 3, capture), now=1.02)
    assert "lidar" not in legacy.health


def test_capture_pose_from_wrong_origin_stops_without_mapping_points():
    session, status, capture, local = scenario("cpu_capture")
    capture[0, 3] += 1
    session.feed_lidar(LidarScan(0, 1, 1700000000000000000, local, 1, 3, capture), now=1)
    session.set_goal((18, 10))
    assert session.step(status, now=1.01) == (0, 0)
    assert session.state == "waiting_for_sensors"
    assert "disagrees" in session.error
    assert session.grid.revision == 0
