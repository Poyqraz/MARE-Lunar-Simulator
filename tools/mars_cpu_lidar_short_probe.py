"""Supervised 2 m simulation probe for the experimental CPU LiDAR mode.

This sends one goal and a stop to the local simulation service. The operator
must watch the scene. Synchronous HTTP requests and sampled poses mean the
duration and distance limits are not hard real-time or collision guarantees.

Remaining race: the goal is posted after the authorizing snapshot, so a new map
revision or a stale sensor can still appear before the service receives it.
The service plans its own route on its live map and refuses every motion
decision without fresh sensors; this probe then stops on a replan (unless
allowed), a session or mission change, or a long sensor wait. It does not
prevent that window, it only bounds what happens after it.
"""

import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import mars_lidar_turn_probe as common  # noqa: E402

DISTANCE_M = 2.0
OFFSET_RAD = math.radians(25)
MAX_DURATION_S = 35.0
MAX_DISPLACEMENT_M = 2.5
MAX_SAMPLED_PATH_M = 3.0
MAX_SENSOR_WAIT_S = 3.0
# Bounded wait for a sample captured after route planning: five 5 Hz ground-truth periods.
POST_PLAN_WAIT_S = 1.0
POST_PLAN_POLL_S = 0.025


def _cpu(snapshot):
    if snapshot.get("lidar_pose_source") != "cpu_capture":
        raise ValueError("Servis cpu_capture modunda degil")
    sensor = (snapshot.get("sensor_health") or {}).get("lidar") or {}
    if sensor.get("pose_source") != "cpu_capture":
        raise common.SensorPreflightNotReady("Gecerli CPU LiDAR capture pozu bekleniyor")


def _straight_goal(context):
    """Default goal: 2 m ahead with a 25 degree offset, on an open inflated segment."""
    position, direction = context["position_m"], context["heading_rad"] + OFFSET_RAD
    goal = (position[0] + DISTANCE_M * math.cos(direction),
            position[1] + DISTANCE_M * math.sin(direction))
    if not common._segment_is_open(context["grid"], position[:2], goal):
        raise ValueError("Kisa testin haritadaki sisirilmis yolunda kapali hucre var")
    return {"goal_m": goal, "details": {"heading_offset_deg": math.degrees(OFFSET_RAD)}}


def _cross_track_m(point, route):
    """Horizontal distance from a sampled pose to the planned polyline."""
    best = math.inf
    for a, b in zip(route, route[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length2))
        best = min(best, math.dist(point, (a[0] + t * dx, a[1] + t * dy)))
    return best


def _stale_reason(snapshot, elapsed):
    """The existing freshness limits for one snapshot, counting `elapsed` request and processing time."""
    pose_age = snapshot.get("pose_age_s")
    if type(pose_age) not in (float, int) or not math.isfinite(pose_age) or pose_age + elapsed > 0.3:
        return "Poz, on kontrol sirasinda eskidi"
    for name in ("lidar", "ground_truth"):
        sensor = snapshot["sensor_health"][name]
        lag_s = (common._stamp(snapshot["live_pose"]["stamp_ns"]) - common._stamp(sensor["stamp_ns"])) / 1e9
        if sensor["received_age_s"] + elapsed > 0.35 or lag_s + elapsed > 0.35:
            return f"{name} verisi on kontrol sirasinda eskidi"
        if sensor.get("capture_stale") or type(sensor.get("valid_inside_points")) is not int                 or sensor["valid_inside_points"] < 1:
            return f"{name} gecerli nokta icermiyor"
    return None


def _authorize_after_planning(get, *, now, sleep, planned, session, revision, position, heading):
    """Wait, bounded, for a snapshot newer than the planning one that passes the unchanged limits.

    Route planning (~0.1 s on a 1281 m map) used to count against the 0.35 s sensor limit. Here it
    does not age the data: the authorizing snapshot is taken after planning, must carry captures newer
    than the planned ones, and is judged with only its own request time. The session, map revision
    and stationary pose must still equal the ones the route was planned on.
    """
    deadline = now() + POST_PLAN_WAIT_S
    old = {name: common._stamp(planned["sensor_health"][name]["stamp_ns"]) for name in ("lidar", "ground_truth")}
    while True:
        started = now()
        snapshot = get("/mission/snapshot")
        try:
            _cpu(snapshot)
            current, current_heading, _ = common._stationary(snapshot)
        except common.SensorPreflightNotReady:  # a stale sample: keep waiting until the deadline
            if now() >= deadline:
                raise
            sleep(min(POST_PLAN_POLL_S, max(0.0, deadline - now())))
            continue
        common._bridge_stationary(get("bridge"))
        elapsed = max(0.0, now() - started)
        drift = abs(math.atan2(math.sin(current_heading - heading), math.cos(current_heading - heading)))
        if (snapshot.get("session_id") != session or math.dist(current[:2], position[:2]) > 0.02
                or drift > 0.02):
            raise ValueError("Oturum veya roverin durgunlugu planlamadan sonra degisti")
        if snapshot.get("map_revision") != revision:
            raise common.SensorPreflightNotReady("Harita planlama sirasinda degisti; yeniden planlanacak")
        newer = all(common._stamp(snapshot["sensor_health"][name]["stamp_ns"]) > stamp for name, stamp in old.items())
        reason = _stale_reason(snapshot, elapsed) if newer else "Planlamadan sonra yeni sensor ornegi bekleniyor"
        if reason is None:
            return snapshot, elapsed
        if now() >= deadline:
            raise common.SensorPreflightNotReady(reason)
        sleep(min(POST_PLAN_POLL_S, max(0.0, deadline - now())))


def _preflight(get, *, now, choose_goal=_straight_goal, sleep=time.sleep):
    first = get("/mission/snapshot")
    _cpu(first)
    start, heading, _ = common._stationary(first)
    common._bridge_stationary(get("bridge"))
    grid = get("/map")
    second = get("/mission/snapshot")
    _cpu(second)
    position, current_heading, _ = common._stationary(second)
    common._bridge_stationary(get("bridge"))
    session = first.get("session_id")
    angular_drift = abs(math.atan2(math.sin(current_heading - heading), math.cos(current_heading - heading)))
    revision = grid.get("revision")
    if (not isinstance(session, str) or not session or session != second.get("session_id")
            or type(revision) is not int or revision < 0
            or second.get("map_revision") != grid.get("revision")
            or math.dist(start[:2], position[:2]) > 0.02 or angular_drift > 0.02):
        raise ValueError("Oturum, harita veya roverin durgunlugu degisti")
    planning_started = now()
    plan = choose_goal({"session_id": session, "map_revision": revision, "grid": grid, "snapshot": second,
                        "position_m": position, "heading_rad": current_heading})
    planned_at = now()
    authorizing, elapsed = _authorize_after_planning(get, now=now, sleep=sleep, planned=second, session=session,
                                                     revision=revision, position=position, heading=current_heading)
    health, pose_stamp = authorizing["sensor_health"], common._stamp(authorizing["live_pose"]["stamp_ns"])
    freshness = {"planning_s": planned_at - planning_started, "post_planning_wait_s": now() - planned_at,
                 "authorizing_elapsed_s": elapsed, "pose_age_s": authorizing["pose_age_s"]}
    for name in ("lidar", "ground_truth"):
        freshness[f"{name}_stamp_ns"] = health[name]["stamp_ns"]
        freshness[f"{name}_lag_s"] = (pose_stamp - common._stamp(health[name]["stamp_ns"])) / 1e9
        freshness[f"{name}_received_age_s"] = health[name]["received_age_s"]
    return {"session_id": session, "position_m": position, "heading_rad": current_heading,
            "map_revision": grid.get("revision"), "freshness": freshness, **plan}


def _wait_for_preflight(get, *, now, sleep, log, wait_s=10, choose_goal=_straight_goal):
    deadline = now() + wait_s
    announced = False
    while True:
        try:
            ready = _preflight(get, now=now, choose_goal=choose_goal, sleep=sleep)
            if now() > deadline:
                raise common.SensorPreflightNotReady("On kontrol suresi doldu")
            return ready
        except common.SensorPreflightNotReady as error:
            remaining = deadline - now()
            if remaining <= 0:
                raise ValueError(f"Sensorler tazelenmedi: {error}") from error
            if not announced:
                log("SENSOR_BEKLENIYOR: taze veri icin en fazla yaklasik 10 sn; hedef gonderilmedi.")
                announced = True
            sleep(min(0.25, remaining))


def run(*, get=common._get, post=common._post, now=time.monotonic, sleep=time.sleep, log=print,
        choose_goal=_straight_goal):
    ready = _wait_for_preflight(get, now=now, sleep=sleep, log=log, choose_goal=choose_goal)
    log("MARS_CPU_ON_KONTROL: " + json.dumps({"session_id": ready["session_id"],
                                             "start_m": ready["position_m"], "goal_m": ready["goal_m"],
                                             **ready.get("details", {}),
                                             "map_revision": ready["map_revision"],
                                             "freshness": ready["freshness"]}, ensure_ascii=False))
    limits = {"duration_s": MAX_DURATION_S, "displacement_m": MAX_DISPLACEMENT_M,
              "sampled_path_m": MAX_SAMPLED_PATH_M, **ready.get("limits", {})}
    route = ready.get("route_m")
    allow_replan = ready.get("allow_replan") is True
    max_cross_track = 0.0 if route else None
    map_revisions, plan_revisions = [], []
    attempted = confirmed = stop_ok = False
    reason, error, mission_id, final_status = "timeout", None, None, None
    first_position = tuple(ready["position_m"][:2])
    previous_position, sampled_path, wait_started = first_position, 0.0, None
    last_message = None
    started = now()
    try:
        attempted = True  # A timed-out request may still have reached the service.
        ack = post("/goal", {"x": ready["goal_m"][0], "y": ready["goal_m"][1]})
        goal_ack = ack.get("goal") if isinstance(ack, dict) else None
        if (not isinstance(ack, dict) or ack.get("ok") is not True
                or not isinstance(goal_ack, (tuple, list)) or len(goal_ack) != 2
                or math.dist(goal_ack, ready["goal_m"]) > 1e-6):
            raise ValueError("Hedef yaniti onaylanmadi")
        confirmed = True
        while now() - started < limits["duration_s"]:
            snapshot = get("/mission/snapshot")
            mission = snapshot.get("mission") or {}
            live = snapshot.get("live_pose") or {}
            current = live.get("position_m")
            state = snapshot.get("state")
            if snapshot.get("session_id") != ready["session_id"]:
                reason = "session_changed"
                break
            if not isinstance(mission, dict) or not isinstance(mission.get("mission_id"), str):
                reason = "mission_missing"
                break
            if mission_id is None:
                mission_id = mission["mission_id"]
            target = mission.get("goal")
            if (mission["mission_id"] != mission_id or not isinstance(target, (list, tuple)) or len(target) != 2
                    or math.dist(target, ready["goal_m"]) > 1e-6):
                reason = "mission_changed"
                break
            if snapshot.get("lidar_pose_source") != "cpu_capture":
                reason = "lidar_pose_source_changed"
                break
            sensor = (snapshot.get("sensor_health") or {}).get("lidar") or {}
            if sensor.get("pose_source") != "cpu_capture":
                reason = "lidar_unavailable"
                break
            if snapshot.get("pose_fresh") is not True or snapshot.get("capture_clock_advancing") is not True:
                reason = "pose_stale"
                break
            if (not isinstance(current, (list, tuple)) or len(current) != 3
                    or any(type(v) not in (float, int) or not math.isfinite(v) for v in current)):
                reason = "pose_unavailable"
                break
            current_xy = tuple(current[:2])
            sampled_path += math.dist(previous_position, current_xy)
            previous_position = current_xy
            if (math.dist(first_position, current_xy) > limits["displacement_m"]
                    or sampled_path > limits["sampled_path_m"]):
                reason = "distance_limit"
                break
            if route:
                active = mission.get("active_plan")
                if allow_replan and isinstance(active, list) and len(active) >= 2:
                    # After a replan the service follows its new plan; measure against that.
                    route = [tuple(p[:2]) for p in active]
                max_cross_track = max(max_cross_track, _cross_track_m(current_xy, route))
                if max_cross_track > ready["max_cross_track_m"]:
                    reason = "route_deviation"
                    break
            if snapshot.get("map_revision") not in map_revisions:
                map_revisions.append(snapshot.get("map_revision"))
            if mission.get("plan_revision") not in plan_revisions:
                plan_revisions.append(mission.get("plan_revision"))
            message = (state, mission.get("plan_revision"), snapshot.get("map_revision"))
            if message != last_message:
                log(f"{now() - started:.1f} s | durum={state} | poz={list(current_xy)} | "
                    f"plan={mission.get('plan_revision')} | harita={snapshot.get('map_revision')}")
                last_message = message
            if state in ("arrived", "blocked", "stalled_or_timed_out", "disconnected"):
                reason = str(state)
                break
            if not allow_replan and (state == "replanning" or (type(mission.get("plan_revision")) is int
                                                               and mission["plan_revision"] > 1)):
                reason = "replanning_detected"
                break
            if state == "waiting_for_pose":
                reason = str(state)
                break
            # The service already commands zero in both states; bound only how long they last continuously.
            if state in ("waiting_for_sensors", "waiting_for_fresh_data"):
                wait_started = now() if wait_started is None else wait_started
                if now() - wait_started > MAX_SENSOR_WAIT_S:
                    reason = "sensor_wait_limit"
                    break
            else:
                wait_started = None
            sleep(0.4)
    except KeyboardInterrupt:
        reason = "interrupted"
    except Exception as exc:
        reason, error = "request_error", str(exc)[:500]
    finally:
        if attempted:
            try:
                result = post("/stop", {})
                stop_ok = isinstance(result, dict) and result.get("ok") is True
                if not stop_ok:
                    raise ValueError("Stop yaniti onay icermiyor")
            except Exception as exc:
                error = (error + "; " if error else "") + "Stop istegi basarisiz: " + str(exc)[:250]
    try:
        final = get("/mission/snapshot")
        final_status = {key: final.get(key) for key in ("session_id", "state", "pose_fresh", "wheel_command_m_s")}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {"reason": reason, "error": error, "goal_confirmed": confirmed,
            "stop_request_succeeded": stop_ok, "start_session_id": ready["session_id"],
            "mission_id": mission_id, "goal_m": ready["goal_m"], "start_position_m": ready["position_m"],
            "sampled_path_m": sampled_path, "max_cross_track_m": max_cross_track,
            "map_revisions_seen": map_revisions, "plan_revisions_seen": plan_revisions,
            "replans_allowed": allow_replan, "final_status": final_status}


def main():
    try:
        summary = run()
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit("ON_KONTROL_BASARISIZ: " + str(error) + "; hedef gonderilmedi.") from error
    print("MARS_CPU_KISA_SURUS: " + json.dumps(summary, ensure_ascii=False, allow_nan=False), flush=True)
    if not summary["stop_request_succeeded"]:
        raise SystemExit("DURDURMA ISTEGI BASARISIZ: Unreal'da Stop dugmesine basin")
    if not summary["goal_confirmed"]:
        raise SystemExit("HEDEF YANITI BELIRSIZ: Unreal'da Stop dugmesini kontrol edin")


if __name__ == "__main__":
    main()
