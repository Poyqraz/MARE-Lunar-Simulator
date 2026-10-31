"""Run a bounded, preflight-checked simulated turn for opt-in LiDAR pose diagnosis.

This tool explicitly sends a goal and then a stop to the local simulation API.
It rejects stale pose/sensors, active missions, nonzero wheel commands, blocked
paths and missing current pose logs before sending a goal. It is not hardware
control or a certified safety system; keep the Unreal Stop button accessible.
"""

import json
import math
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.analyze_mars_lidar_pose import analyze  # noqa: E402

BASE = "http://127.0.0.1:8766"
BRIDGE = "http://127.0.0.1:8765/status"
STOP_STATES = {"arrived", "blocked", "stalled_or_timed_out", "disconnected"}


def _get(path):
    url = BRIDGE if path == "bridge" else BASE + path
    with urlopen(url, timeout=3) as response:
        return json.load(response)


def _post(path, body):
    request = Request(BASE + path, data=json.dumps(body).encode("utf-8"), method="POST",
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=3) as response:
        return json.load(response)


def _stamp(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).isascii() or not str(value).isdigit():
        raise ValueError("Eksik veya gecersiz zaman damgasi")
    stamp = int(value)
    if not 0 < stamp <= 2**63 - 1:
        raise ValueError("Zaman damgasi desteklenen aralik disinda")
    return stamp


def _stationary(snapshot):
    if snapshot.get("position_source") != "simulation telemetry" or snapshot.get("depth_source") != "ground_truth":
        raise ValueError("Beklenen simulator telemetrisi ve ground_truth derinligi gerekli")
    if (snapshot.get("state") not in ("idle", "new_session_requires_goal")
            or snapshot.get("pose_fresh") is not True or snapshot.get("capture_clock_advancing") is not True):
        raise ValueError("Durum bos, poz taze ve saat ilerliyor olmali")
    mission = snapshot.get("mission")
    if mission is not None and (not isinstance(mission, dict) or mission.get("closed") is not True):
        raise ValueError("Aktif gorev var")
    speed = snapshot.get("speed_estimate_m_s")
    if type(speed) not in (int, float) or not math.isfinite(speed) or not 0 <= speed <= 0.01:
        raise ValueError("Rover durgun degil veya hiz tahmini yok")
    wheels = snapshot.get("wheel_command_m_s") or {}
    if any(type(wheels.get(k)) not in (int, float) or not math.isfinite(wheels[k]) or abs(wheels[k]) > 1e-9
           for k in ("FL", "FR", "BL", "BR")):
        raise ValueError("Teker komutlari sifir degil veya eksik")
    pose = snapshot.get("live_pose") or {}
    position, heading = pose.get("position_m"), pose.get("heading_rad")
    if (not isinstance(position, (list, tuple)) or len(position) != 3
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in position)
            or type(heading) not in (int, float) or not math.isfinite(heading)):
        raise ValueError("Rover pozu eksik veya gecersiz")
    pose_stamp = _stamp(pose.get("stamp_ns"))
    for name in ("lidar", "ground_truth"):
        sensor = (snapshot.get("sensor_health") or {}).get(name) or {}
        age, count = sensor.get("received_age_s"), sensor.get("valid_inside_points")
        lag = pose_stamp - _stamp(sensor.get("stamp_ns"))
        if (sensor.get("capture_stale") is True or type(age) not in (int, float) or not math.isfinite(age)
                or not 0 <= age <= 0.35 or type(count) is not int or count < 20
                or not -1024 <= lag <= 350_000_000):
            raise ValueError(f"{name} verisi yeterince taze degil")
    return tuple(position), float(heading), pose_stamp


def _bridge_stationary(status):
    if status.get("connected") is not True or status.get("telemetry_format") != "unreal-tr-v1":
        raise ValueError("Rover baglantisi veya tr-TR telemetri bicimi uygun degil")
    wheels = status.get("wheel_command_m_s") or {}
    if any(type(wheels.get(k)) not in (int, float) or not math.isfinite(wheels[k]) or abs(wheels[k]) > 1e-9
           for k in ("FL", "FR", "BL", "BR")):
        raise ValueError("Rover koprusundeki teker komutlari sifir degil veya eksik")
    telemetry = status.get("telemetry_unreal") or {}
    angular = [telemetry.get(k) for k in ("wx", "wy", "wz")]
    if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 0.01 for v in angular):
        raise ValueError("Acil donus hizi sifira yakin degil")
    age = status.get("telemetry_age_s")
    if type(age) not in (int, float) or not math.isfinite(age) or not 0 <= age <= 0.3:
        raise ValueError("Ham rover telemetrisi taze degil")


def _segment_is_open(grid, start, goal):
    w, h, res, blocked = grid.get("width"), grid.get("height"), grid.get("resolution_m"), grid.get("blocked")
    if (type(w) is not int or type(h) is not int or min(w, h) < 3 or w * h > 2_000_000
            or type(res) not in (int, float) or not math.isfinite(res) or res <= 0
            or not isinstance(blocked, list) or len(blocked) != w * h):
        raise ValueError("Harita bicimi gecersiz")

    def cell(point):
        x, y = point
        if not (0 <= x <= (w - 1) * res and 0 <= y <= (h - 1) * res):
            raise ValueError("Donus hedefi harita disinda")
        return int(math.floor(y / res + 0.5)), int(math.floor(x / res + 0.5))

    previous = None
    n = max(1, math.ceil(math.dist(start, goal) / (res / 4)))
    for i in range(n + 1):
        t = i / n
        row, col = cell((start[0] + t * (goal[0] - start[0]), start[1] + t * (goal[1] - start[1])))
        if blocked[row * w + col] != 0:
            return False
        if previous and row != previous[0] and col != previous[1]:
            if blocked[row * w + previous[1]] != 0 or blocked[previous[0] * w + col] != 0:
                return False
        previous = row, col
    return True


def run(log_path, *, get=_get, post=_post, analyzer=analyze, now=time.monotonic, sleep=time.sleep):
    """Aim to stop after 8 seconds or 45 degrees, including a stop on request errors.

    Synchronous HTTP calls can overrun the target duration. This is an
    operator-supervised simulation diagnostic, not a real-time watchdog.
    """
    first = get("/mission/snapshot")
    start, heading, first_stamp = _stationary(first)
    _bridge_stationary(get("bridge"))
    grid = get("/map")
    goal = (start[0] - 2 * math.cos(heading), start[1] - 2 * math.sin(heading))
    if not _segment_is_open(grid, start[:2], goal):
        raise ValueError("Hedefe giden sisirilmis harita hucresi kapali")
    log1 = analyzer(log_path, window_s=10)
    if log1.get("status") != "matched" or not log1.get("last_capture_stamp_ns"):
        raise ValueError("Eslesen LiDAR pose logu yok; PIE tani etiketini ve derlemeyi kontrol edin")
    sleep(1)
    log2 = analyzer(log_path, window_s=10)
    if (log2.get("status") != "matched" or not log2.get("last_capture_stamp_ns")
            or _stamp(log2["last_capture_stamp_ns"]) <= _stamp(log1["last_capture_stamp_ns"])):
        raise ValueError("LiDAR pose logu ilerlemiyor; hedef gonderilmedi")
    second = get("/mission/snapshot")
    position, current_heading, start_stamp = _stationary(second)
    _bridge_stationary(get("bridge"))
    if (not first.get("session_id") or second.get("session_id") != first["session_id"]
            or second.get("map_revision") != grid.get("revision")
            or math.dist(start[:2], position[:2]) > 0.02
            or abs(math.atan2(math.sin(current_heading - heading), math.cos(current_heading - heading))) > 0.02
            or abs(start_stamp - _stamp(log2["last_capture_stamp_ns"])) > 1_000_000_000):
        raise ValueError("Oturum, harita, durgunluk veya log tazeligi degisti; hedef gonderilmedi")

    snapshots, reason, error = [], "timeout", None
    previous_position, sampled_path_m = start[:2], 0.0
    goal_confirmed, stop_ok = False, False
    attempted = False
    start_time = now()
    try:
        attempted = True  # A timed-out goal request may nevertheless have been accepted.
        acknowledgement = post("/goal", {"x": goal[0], "y": goal[1]})
        if not isinstance(acknowledgement, dict) or acknowledgement.get("ok") is not True:
            raise ValueError("Hedef istegi onaylanmadi")
        goal_confirmed = True
        while now() - start_time < 8:
            s = get("/mission/snapshot")
            current = s.get("live_pose") or {}
            snapshots.append({"elapsed_s": max(0.0, now() - start_time), "state": s.get("state"),
                              "session_id": s.get("session_id"), "live_pose": current,
                              "sensor_wait_details": s.get("sensor_wait_details"), "mission": s.get("mission")})
            if s.get("session_id") != first["session_id"]:
                reason = "session_changed"
                break
            if s.get("state") in STOP_STATES:
                reason = str(s["state"])
                break
            if s.get("pose_fresh") is not True or s.get("capture_clock_advancing") is not True:
                reason = "pose_stale"
                break
            p, h = current.get("position_m"), current.get("heading_rad")
            if (not isinstance(p, (list, tuple)) or len(p) != 3
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in p)
                    or type(h) not in (int, float) or not math.isfinite(h)):
                reason = "pose_unavailable"
                break
            sampled_path_m += math.dist(previous_position, p[:2])
            previous_position = tuple(p[:2])
            if math.dist(start[:2], p[:2]) > 0.2 or sampled_path_m > 0.2:
                reason = "translation_limit"
                break
            turn = abs(math.atan2(math.sin(h - heading), math.cos(h - heading)))
            if turn >= math.radians(45):
                reason = "turn_observed"
                break
            sleep(0.25)
    except Exception as exc:
        reason, error = "request_error", str(exc)[:500]
    finally:
        if attempted:
            try:
                acknowledgement = post("/stop", {})
                stop_ok = isinstance(acknowledgement, dict) and acknowledgement.get("ok") is True
                if not stop_ok:
                    raise ValueError("Stop yaniti onay icermiyor")
            except Exception as exc:
                error = (error + "; " if error else "") + "Stop istegi basarisiz: " + str(exc)[:250]

    # Let Unreal flush the final tagged log lines after the stop.
    sleep(1)
    end_stamp, final_status = None, None
    try:
        final = get("/mission/snapshot")
        if final.get("session_id") == first["session_id"]:
            end_stamp = _stamp((final.get("live_pose") or {}).get("stamp_ns")) + 1024
            final_status = {key: final.get(key) for key in ("state", "pose_fresh", "wheel_command_m_s")}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        comparison = analyzer(log_path, window_s=30, start_stamp_ns=max(1, first_stamp - 1024),
                              end_stamp_ns=end_stamp)
    except Exception as exc:
        comparison = {"status": "analysis_error", "error": str(exc)[:500]}
    try:
        mission_export, export_error = get("/mission/export"), None
    except Exception as exc:
        mission_export, export_error = None, str(exc)[:500]
    return {"reason": reason, "error": error, "goal_confirmed": goal_confirmed,
            "stop_request_succeeded": stop_ok, "final_status": final_status,
            "start_session_id": first["session_id"], "start_position_m": start, "start_heading_rad": heading,
            "goal_m": goal, "snapshot_count": len(snapshots), "sampled_path_m": sampled_path_m,
            "snapshots": snapshots,
            "pose_comparison": comparison, "mission_export": mission_export, "mission_export_error": export_error}


def main():
    log = ROOT / "Saved/Logs/Moon_Simulator.log"
    try:
        result = run(log)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit("ON_KONTROL_BASARISIZ: " + str(error)) from error
    output = ROOT / "Saved/Mars" / f"lidar-donus-{uuid.uuid4().hex}.json"
    summary = {k: v for k, v in result.items() if k not in ("snapshots", "mission_export")}
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
    except (OSError, ValueError) as error:
        print("KAYIT_YAZILAMADI:", error, flush=True)
        output = None
    print("MARS_LIDAR_TURN:", json.dumps(summary, ensure_ascii=False, allow_nan=False), flush=True)
    if output is not None:
        print("KAYIT:", output, flush=True)
    if not result["stop_request_succeeded"]:
        raise SystemExit("DURDURMA ISTEGI BASARISIZ: Unreal'da Stop dugmesine basin")
    if not result["goal_confirmed"]:
        raise SystemExit("HEDEF YANITI BELIRSIZ: Unreal'da Stop dugmesine basin")


if __name__ == "__main__":
    main()
