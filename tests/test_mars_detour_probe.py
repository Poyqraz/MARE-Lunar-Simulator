import numpy as np
import pytest

from mars_rover.planning import TerrainMap
from test_mars_cpu_lidar_short_probe import Simulation
from tools import mars_cpu_lidar_short_probe as short
from tools import mars_detour_probe as probe

HASH = "a" * 64
GOAL = (12.0, 5.0)


def scene(cube=True):
    """20 x 20 m flat static map, rover at (5, 5) facing +x, optional 1 x 3 cell obstacle at x=8."""
    static = TerrainMap(np.zeros((20, 20)), 1.0)
    static.manifest_sha256 = HASH
    raw = static.raw_blocked.copy()
    if cube:
        raw[4:7, 8] = True
    sim = Simulation()
    sim.start["terrain_manifest_sha256"] = HASH
    sim.grid["blocked"] = static._inflate(raw).astype(int).ravel().tolist()
    return static, sim


def preflight(sim, chooser):
    return short._wait_for_preflight(sim.get, now=sim.now, sleep=sim.sleep, log=lambda _: None,
                                     choose_goal=chooser)


@pytest.mark.parametrize("cube,expected", [(True, "pre_existing_obstacle_detour"), (False, "open_direct_route")])
def test_preview_plans_on_the_live_map_and_sends_nothing(cube, expected):
    static, sim = scene(cube)
    result = preflight(sim, probe.goal_chooser(static, GOAL))["preview"]
    assert sim.calls == []
    assert result["test_type"] == expected
    assert result["direct_segment_open"] is (not cube)
    assert result["session_id"] == "session" and result["map_revision"] == 0
    if cube:
        assert result["route_length_m"] > result["straight_distance_m"] + 0.5
        assert result["dynamic_inflated_cells"] > 0
        trial = probe.live_terrain(static, sim.start, sim.grid)
        assert all(trial.segment_clear(a, b) for a, b in zip(result["route_m"], result["route_m"][1:]))


def test_send_requires_the_previewed_session_and_map_revision():
    for session, revision in (("old-session", 0), ("session", 1)):
        static, sim = scene()
        chooser = probe.goal_chooser(static, GOAL, expect_session=session, expect_map_revision=revision)
        with pytest.raises(ValueError, match="onizlemeden farkli"):
            short.run(get=sim.get, post=sim.post, now=sim.now, sleep=sim.sleep, log=lambda _: None,
                      choose_goal=chooser)
        assert sim.calls == []


@pytest.mark.parametrize("mismatch", ["manifest", "static_block_missing", "shape"])
def test_live_map_mismatch_fails_closed_before_any_goal(mismatch):
    static, sim = scene()
    if mismatch == "manifest":
        sim.start["terrain_manifest_sha256"] = "b" * 64
    elif mismatch == "static_block_missing":
        sim.grid["blocked"][0] = 0
    else:
        sim.grid["width"] = 21
    with pytest.raises(ValueError):
        preflight(sim, probe.goal_chooser(static, GOAL))
    assert sim.calls == []


def test_supervised_detour_arrives_and_reports_route_metrics():
    static, sim = scene()
    chooser = probe.goal_chooser(static, GOAL, expect_session="session", expect_map_revision=0)
    result = short.run(get=sim.get, post=sim.post, now=sim.now, sleep=sim.sleep, log=lambda _: None,
                       choose_goal=chooser)
    assert result["reason"] == "arrived" and sim.calls == ["/goal", "/stop"]
    assert sim.goal == GOAL
    assert 0 <= result["max_cross_track_m"] <= probe.MAX_CROSS_TRACK_M
    assert result["map_revisions_seen"] == [0]


@pytest.mark.parametrize("allow,reason", [(False, "replanning_detected"), (True, "arrived")])
def test_replans_stop_by_default_and_are_reported_when_allowed(allow, reason):
    static, sim = scene()
    sim.states = ["following", "replanning", "following", "arrived"]
    chooser = probe.goal_chooser(static, GOAL, expect_session="session", expect_map_revision=0, allow_replan=allow)
    result = short.run(get=sim.get, post=sim.post, now=sim.now, sleep=sim.sleep, log=lambda _: None,
                       choose_goal=chooser)
    assert result["reason"] == reason and result["replans_allowed"] is allow
    assert sim.calls == ["/goal", "/stop"] and result["stop_request_succeeded"]


def test_cross_track_deviation_stops_the_drive():
    static, sim = scene()
    sim.position = [4.0, 5.0, 1.0]  # 1 m behind the route start
    chooser = probe.goal_chooser(static, GOAL, expect_session="session", expect_map_revision=0)
    result = short.run(get=sim.get, post=sim.post, now=sim.now, sleep=sim.sleep, log=lambda _: None,
                       choose_goal=chooser)
    assert result["reason"] == "route_deviation"
    assert result["max_cross_track_m"] > probe.MAX_CROSS_TRACK_M
    assert sim.calls == ["/goal", "/stop"] and result["stop_request_succeeded"]


def test_send_without_preview_values_is_rejected_before_network_use():
    calls = []
    with pytest.raises(SystemExit):
        probe.main(["--goal", "1", "2", "--send"], get=lambda p: calls.append(p), post=lambda *a: calls.append(a))
    assert calls == []
