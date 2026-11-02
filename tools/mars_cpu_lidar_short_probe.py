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


def _preflight(get, *, now):
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
    direction = current_heading + OFFSET_RAD
    goal = (position[0] + DISTANCE_M * math.cos(direction),
            position[1] + DISTANCE_M * math.sin(direction))
    if not common._segment_is_open(grid, position[:2], goal):
        raise ValueError("Kisa testin haritadaki sisirilmis yolunda kapali hucre var")
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
            "goal_m": goal, "map_revision": grid.get("revision")}


def _wait_for_preflight(get, *, now, sleep, log, wait_s=10):
    deadline = now() + wait_s
    announced = False
    while True:
        try:
            ready = _preflight(get, now=now)
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


def run(*, get=common._get, post=common._post, now=time.monotonic, sleep=time.sleep, log=print):
    ready = _wait_for_preflight(get, now=now, sleep=sleep, log=log)
    log("MARS_CPU_ON_KONTROL: " + json.dumps({"session_id": ready["session_id"],
                                             "start_m": ready["position_m"], "goal_m": ready["goal_m"],
                                             "heading_offset_deg": math.degrees(OFFSET_RAD),
                                             "map_revision": ready["map_revision"]}, ensure_ascii=False))
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
        while now() - started < MAX_DURATION_S:
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
            if math.dist(first_position, current_xy) > MAX_DISPLACEMENT_M or sampled_path > MAX_SAMPLED_PATH_M:
                reason = "distance_limit"
                break
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
            "sampled_path_m": sampled_path, "final_status": final_status}


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
