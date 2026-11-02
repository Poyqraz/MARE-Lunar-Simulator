import copy
import math

import pytest

from tools import mars_cpu_lidar_short_probe as probe


STAMP = 1700000000000000000
ZERO = {key: 0.0 for key in ("FL", "FR", "BL", "BR")}


def snapshot():
    sensor = {"valid_inside_points": 1000, "received_age_s": 0.05, "stamp_ns": str(STAMP)}
    return {"session_id": "session", "state": "idle", "position_source": "simulation telemetry",
            "depth_source": "ground_truth", "lidar_pose_source": "cpu_capture",
            "pose_fresh": True, "capture_clock_advancing": True, "pose_age_s": 0.02,
            "speed_estimate_m_s": 0.0, "wheel_command_m_s": dict(ZERO), "map_revision": 0,
            "live_pose": {"position_m": [5.0, 5.0, 1.0], "heading_rad": 0.0, "stamp_ns": str(STAMP)},
            "sensor_health": {"lidar": {**sensor, "pose_source": "cpu_capture"}, "ground_truth": dict(sensor)},
            "mission": None}


class Simulation:
    def __init__(self):
        self.clock = 0.0
        self.start = snapshot()
        self.grid = {"width": 20, "height": 20, "resolution_m": 1, "revision": 0, "blocked": [0] * 400}
        self.bridge = {"connected": True, "telemetry_format": "unreal-tr-v1", "telemetry_age_s": 0.01,
                       "wheel_command_m_s": dict(ZERO), "telemetry_unreal": {"wx": 0, "wy": 0, "wz": 0}}
        self.goal = None
        self.calls = []
        self.states = ["following", "arrived"]
        self.stopped = False
        self.goal_error = self.stop_error = False
        self.changed_session = False
        self.bridge_delay = 0.0
        self.position = [5.2, 5.0, 1.0]
        self.monitor_lidar_missing = False

    def now(self):
        return self.clock

    def sleep(self, duration):
        self.clock += duration

    def get(self, path):
        if path == "bridge":
            self.clock += self.bridge_delay
            return copy.deepcopy(self.bridge)
        if path == "/map":
            return copy.deepcopy(self.grid)
        assert path == "/mission/snapshot"
        data = copy.deepcopy(self.start)
        if self.goal is not None and not self.stopped:
            data["state"] = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            data["mission"] = {"mission_id": "mission", "goal": list(self.goal), "plan_revision": 1}
            data["live_pose"]["position_m"] = self.position
            if self.monitor_lidar_missing:
                data["sensor_health"].pop("lidar")
            if self.changed_session:
                data["session_id"] = "new-session"
        return data

    def post(self, path, body):
        self.calls.append(path)
        if path == "/goal":
            self.goal = (body["x"], body["y"])
            if self.goal_error:
                raise TimeoutError("goal response timed out")
            return {"ok": True, "goal": self.goal}
        assert path == "/stop"
        self.stopped = True
        if self.stop_error:
            raise TimeoutError("stop failed")
        return {"ok": True}

    def run(self):
        return probe.run(get=self.get, post=self.post, now=self.now, sleep=self.sleep, log=lambda _: None)


def test_short_probe_aims_two_metres_with_a_small_turn_and_stops_after_arrival():
    sim = Simulation()
    result = sim.run()
    assert result["reason"] == "arrived"
    assert result["goal_confirmed"] and result["stop_request_succeeded"]
    assert sim.calls == ["/goal", "/stop"]
    assert math.dist(sim.goal, [5, 5]) == pytest.approx(2)
    assert math.atan2(sim.goal[1] - 5, sim.goal[0] - 5) == pytest.approx(math.radians(25))
    assert result["final_status"]["wheel_command_m_s"] == ZERO


@pytest.mark.parametrize("invalid", ["wrong_mode", "blocked", "map_revision", "stale", "slow_preflight"])
def test_preflight_never_sends_motion_for_invalid_or_stale_inputs(invalid):
    sim = Simulation()
    if invalid == "wrong_mode":
        sim.start["lidar_pose_source"] = "telemetry"
    elif invalid == "blocked":
        sim.grid["blocked"][5 * 20 + 6] = 1
    elif invalid == "map_revision":
        sim.grid["revision"] = 1
    elif invalid == "stale":
        sim.start["sensor_health"]["lidar"]["received_age_s"] = 0.5
    else:
        sim.bridge_delay = 0.4
    with pytest.raises(ValueError):
        sim.run()
    assert sim.calls == []


@pytest.mark.parametrize("state,reason", [("replanning", "replanning_detected"),
                                          ("blocked", "blocked"),
                                          ("waiting_for_sensors", "sensor_wait_limit")])
def test_replan_block_or_persistent_sensor_wait_stops_the_test(state, reason):
    sim = Simulation()
    sim.states = [state]
    result = sim.run()
    assert result["reason"] == reason
    assert result["stop_request_succeeded"]
    assert sim.calls == ["/goal", "/stop"]


def test_session_change_or_uncertain_goal_still_requests_stop():
    sim = Simulation()
    sim.changed_session = True
    assert sim.run()["reason"] == "session_changed"
    assert sim.calls == ["/goal", "/stop"]
    sim = Simulation()
    sim.goal_error = True
    result = sim.run()
    assert result["reason"] == "request_error" and result["stop_request_succeeded"]
    assert not result["goal_confirmed"] and sim.calls == ["/goal", "/stop"]


def test_stop_failure_is_reported():
    sim = Simulation()
    sim.stop_error = True
    result = sim.run()
    assert not result["stop_request_succeeded"]
    assert "Stop istegi basarisiz" in result["error"]


def test_distance_limit_or_lost_lidar_stops_the_test():
    sim = Simulation()
    sim.position = [7.6, 5.0, 1.0]
    assert sim.run()["reason"] == "distance_limit"
    assert sim.calls == ["/goal", "/stop"]
    sim = Simulation()
    sim.monitor_lidar_missing = True
    assert sim.run()["reason"] == "lidar_unavailable"
    assert sim.calls == ["/goal", "/stop"]
