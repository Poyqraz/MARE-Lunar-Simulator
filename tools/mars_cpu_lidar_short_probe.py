"""Supervised 2 m simulation probe for the experimental CPU LiDAR mode.

This sends one goal and a stop to the local simulation service. The operator
must watch the scene. Synchronous HTTP requests and sampled poses mean the
duration and distance limits are not hard real-time or collision guarantees.
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


def _preflight(get, *, now, choose_goal=_straight_goal):
    first = get("/mission/snapshot")
    _cpu(first)
    start, heading, _ = common._stationary(first)
    common._bridge_stationary(get("bridge"))
    grid = get("/map")
    snapshot_started = now()
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
    plan = choose_goal({"session_id": session, "map_revision": revision, "grid": grid, "snapshot": second,
                        "position_m": position, "heading_rad": current_heading})
    # Count preflight processing and response time against the existing
    # freshness limits; a slow HTTP call must not authorize an old snapshot.
    elapsed = max(0.0, now() - snapshot_started)
    pose_age = second.get("pose_age_s")
    if type(pose_age) not in (float, int) or not math.isfinite(pose_age) or pose_age + elapsed > 0.3:
        raise common.SensorPreflightNotReady("Poz, on kontrol sirasinda eskidi")
    for name in ("lidar", "ground_truth"):
        sensor = second["sensor_health"][name]
        lag_s = (common._stamp(second["live_pose"]["stamp_ns"]) - common._stamp(sensor["stamp_ns"])) / 1e9
        if sensor["received_age_s"] + elapsed > 0.35 or lag_s + elapsed > 0.35:
            raise common.SensorPreflightNotReady(f"{name} verisi on kontrol sirasinda eskidi")
    return {"session_id": session, "position_m": position, "heading_rad": current_heading,
            "map_revision": grid.get("revision"), **plan}


def _wait_for_preflight(get, *, now, sleep, log, wait_s=10, choose_goal=_straight_goal):
    deadline = now() + wait_s
    announced = False
    while True:
        try:
            ready = _preflight(get, now=now, choose_goal=choose_goal)
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
                                             "map_revision": ready["map_revision"]}, ensure_ascii=False))
    limits = {"duration_s": MAX_DURATION_S, "displacement_m": MAX_DISPLACEMENT_M,
              "sampled_path_m": MAX_SAMPLED_PATH_M, **ready.get("limits", {})}
    route = ready.get("route_m")
    max_cross_track = 0.0 if route else None
    map_revisions = []
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
                max_cross_track = max(max_cross_track, _cross_track_m(current_xy, route))
                if max_cross_track > ready["max_cross_track_m"]:
                    reason = "route_deviation"
                    break
            if snapshot.get("map_revision") not in map_revisions:
                map_revisions.append(snapshot.get("map_revision"))
            message = (state, mission.get("plan_revision"), snapshot.get("map_revision"))
            if message != last_message:
                log(f"{now() - started:.1f} s | durum={state} | poz={list(current_xy)} | "
                    f"plan={mission.get('plan_revision')} | harita={snapshot.get('map_revision')}")
                last_message = message
            if state in ("arrived", "blocked", "stalled_or_timed_out", "disconnected"):
                reason = str(state)
                break
            if state == "replanning" or (type(mission.get("plan_revision")) is int
                                          and mission["plan_revision"] > 1):
                reason = "replanning_detected"
                break
            if state in ("waiting_for_pose", "waiting_for_fresh_data"):
                reason = str(state)
                break
            if state == "waiting_for_sensors":
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
            "map_revisions_seen": map_revisions, "final_status": final_status}


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
