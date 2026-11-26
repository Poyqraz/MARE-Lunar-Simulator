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
        self.snapshots = 0
        self.frozen_sensors = False  # True: no capture newer than the first snapshot ever arrives

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
        # Every snapshot sees a new 5 Hz capture and its matching pose, as the live service does.
        self.snapshots += 1
        tick = str(STAMP + self.snapshots * 200_000_000)
        data["live_pose"]["stamp_ns"] = tick
        for sensor in data["sensor_health"].values():
            if sensor.get("stamp_ns") == str(STAMP) and not self.frozen_sensors:
                sensor["stamp_ns"] = tick
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
                                          ("waiting_for_sensors", "sensor_wait_limit"),
                                          ("waiting_for_fresh_data", "sensor_wait_limit")])
def test_replan_block_or_persistent_sensor_wait_stops_the_test(state, reason):
    sim = Simulation()
    sim.states = [state]
    result = sim.run()
    assert result["reason"] == reason
    assert result["stop_request_succeeded"]
    assert sim.calls == ["/goal", "/stop"]


def test_brief_fresh_data_wait_recovers_and_the_drive_continues():
    sim = Simulation()
    sim.states = ["following", "waiting_for_fresh_data", "following", "arrived"]
    assert sim.run()["reason"] == "arrived"
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


def test_slow_route_planning_is_authorized_by_a_newer_sample_taken_after_it():
    sim = Simulation()
    planned = {}

    def choose(context):
        planned["stamp"] = context["snapshot"]["sensor_health"]["ground_truth"]["stamp_ns"]
        sim.clock += 0.32  # with the 0.05 s receive age, planning alone would exceed 0.35 s
        return probe._straight_goal(context)

    ready = probe._wait_for_preflight(sim.get, now=sim.now, sleep=sim.sleep, log=lambda _: None, choose_goal=choose)
    freshness = ready["freshness"]
    assert int(freshness["ground_truth_stamp_ns"]) > int(planned["stamp"])
    assert freshness["planning_s"] == pytest.approx(0.32)
    assert freshness["authorizing_elapsed_s"] <= 0.35 - 0.05
    assert sim.calls == []


@pytest.mark.parametrize("change", ["frozen_sensors", "stale_newer_sample"])
def test_no_fresh_sample_after_planning_never_authorizes_a_goal(change):
    sim = Simulation()
    if change == "frozen_sensors":
        sim.frozen_sensors = True
    else:
        sim.start["sensor_health"]["ground_truth"]["received_age_s"] = 0.36
    with pytest.raises(ValueError, match="tazelenmedi"):
        sim.run()
    assert sim.calls == []


def test_map_revision_change_after_planning_plans_again_on_the_new_map():
    sim = Simulation()
    revisions = []

    def choose(context):
        revisions.append(context["map_revision"])
        if len(revisions) == 1:  # a new observation lands while the first route is planned
            sim.grid["revision"] = sim.start["map_revision"] = 1
        return probe._straight_goal(context)

    ready = probe._wait_for_preflight(sim.get, now=sim.now, sleep=sim.sleep, log=lambda _: None, choose_goal=choose)
    assert revisions == [0, 1] and ready["map_revision"] == 1


@pytest.mark.parametrize("change", ["session", "pose"])
def test_session_or_pose_change_after_planning_refuses(change):
    sim = Simulation()

    def choose(context):
        if change == "session":
            sim.start["session_id"] = "new-session"
        else:
            sim.start["live_pose"]["position_m"] = [5.05, 5.0, 1.0]
        return probe._straight_goal(context)

    with pytest.raises(ValueError, match="planlamadan sonra"):
        probe._wait_for_preflight(sim.get, now=sim.now, sleep=sim.sleep, log=lambda _: None, choose_goal=choose)
    assert sim.calls == []


def test_a_stale_snapshot_after_planning_is_waited_out_not_fatal():
    sim = Simulation()
    get = sim.get
    stale_polls = []

    def choose(context):
        stale_polls.append(sim.snapshots + 1)  # the first poll after planning sees a stale GT receive age
        return probe._straight_goal(context)

    def flaky_get(path):
        data = get(path)
        if path == "/mission/snapshot" and stale_polls and sim.snapshots == stale_polls[0]:
            data["sensor_health"]["ground_truth"]["received_age_s"] = 0.5
        return data

    ready = probe._preflight(flaky_get, now=sim.now, sleep=sim.sleep, choose_goal=choose)
    assert int(ready["freshness"]["ground_truth_stamp_ns"]) > probe.common._stamp(sim.start["live_pose"]["stamp_ns"])
    assert sim.calls == []
