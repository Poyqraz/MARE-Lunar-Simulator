"""Periodically record local simulation mission diagnostics; sends no commands."""

import argparse
from collections import Counter, defaultdict, deque
import json
import math
import os
from pathlib import Path
import tempfile
import time
import urllib.request
import uuid


def read_local_json(path):
    if path not in ("/mission/snapshot", "/mission/export", "/dashboard/fusion-shadow"):
        raise ValueError("Recorder is restricted to read-only mission and fusion endpoints")
    with urllib.request.urlopen("http://127.0.0.1:8766" + path, timeout=3) as response:
        data = response.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise ValueError("Mission response exceeds recorder limit")
    return json.loads(data)


def atomic_json(path, value):
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".mars-record-", suffix=".tmp", delete=False) as handle:
            temp_name = handle.name
            json.dump(value, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def _stamp(value):
    """Keep nanosecond timestamps exact; never compare rounded JSON floats."""
    if type(value) not in (str, int):
        return None
    raw = str(value)
    if not raw.isascii() or not raw.isdigit() or len(raw) > 19 or not 0 < int(raw) <= 2**63 - 1:
        return None
    return int(raw)


def summarize_fusion(samples, export, tracked_id, *, samples_evicted=0, poll_s=0.75):
    """Summarize exact-session/stamp matches; no missing sample means clear."""
    if not tracked_id:
        return {"status": "no_tracked_mission"}
    missions = export.get("missions") if isinstance(export, dict) else None
    matches = [m for m in missions or [] if isinstance(m, dict) and m.get("mission_id") == tracked_id]
    if len(matches) != 1 or not isinstance(matches[0].get("session_id"), str):
        return {"status": "unavailable", "reason": "Mission/session is missing or ambiguous"}
    mission, session = matches[0], matches[0]["session_id"]
    diag = export.get("obstacle_diagnostics") or {}
    frames = diag.get("frames")
    if diag.get("enabled") is not True or not isinstance(frames, list):
        return {"status": "unavailable", "reason": "Obstacle diagnostics are unavailable"}
    all_by_stamp = defaultdict(list)
    target_frames, target_by_source, unattributed = [], {"lidar": [], "ground_truth": [], "stereo": []}, 0
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        source = frame.get("source")
        if source in target_by_source and frame.get("session_id") == session and frame.get("mission_id") == tracked_id:
            target_by_source[source].append(frame)
        if source != "lidar":
            continue
        if frame.get("mission_id") == tracked_id and frame.get("session_id") != session:
            unattributed += 1
        if frame.get("session_id") != session:
            continue
        stamp = _stamp(frame.get("stamp_ns"))
        if stamp is not None:
            all_by_stamp[stamp].append(frame)
        if (frame.get("mission_id") == tracked_id and "collection_error" not in frame
                and type(frame.get("new_cells_total")) is int and frame["new_cells_total"] > 0):
            target_frames.append(frame)

    statuses = Counter()
    paired = defaultdict(list)
    mission_samples = invalid_comparisons = session_mismatches = 0
    polled_states = Counter()
    last_control = None
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        snapshot = sample.get("snapshot") or {}
        if (not isinstance(snapshot, dict) or snapshot.get("session_id") != session
                or not isinstance(snapshot.get("mission"), dict)
                or snapshot["mission"].get("mission_id") != tracked_id):
            continue
        mission_samples += 1
        if isinstance(snapshot.get("state"), str):
            polled_states[snapshot["state"]] += 1
        if isinstance(snapshot.get("control_timing"), dict):
            last_control = snapshot["control_timing"]
        shadow = sample.get("fusion_shadow")
        if not isinstance(shadow, dict):
            statuses["request_failed" if sample.get("fusion_shadow_error") else "not_recorded"] += 1
            continue
        status = shadow.get("status")
        statuses[status if isinstance(status, str) else "invalid_status"] += 1
        stamp = _stamp(shadow.get("lidar_stamp_ns"))
        if status != "sampled_comparison":
            continue
        if shadow.get("session_id") != session:
            session_mismatches += 1
            continue
        depth_stamp = _stamp(shadow.get("depth_stamp_ns"))
        shared = shadow.get("shared_bins")
        positive = shadow.get("lidar_hazard_depth_ground_like_bins")
        negative = shadow.get("lidar_negative_depth_ground_like_bins")
        if (stamp is None or depth_stamp is None or abs(stamp - depth_stamp) > 250000000
                or type(shared) is not int or shared < 0 or type(positive) is not int or not 0 <= positive <= shared
                or type(negative) is not int or not 0 <= negative <= positive):
            invalid_comparisons += 1
            continue
        paired[stamp].append(shadow)

    matched, ambiguous, missing, invalid_stamp = [], 0, 0, 0
    for frame in target_frames:
        stamp = _stamp(frame.get("stamp_ns"))
        if stamp is None:
            invalid_stamp += 1
        elif stamp not in paired:
            missing += 1
        elif len(all_by_stamp[stamp]) != 1:
            ambiguous += 1
        else:
            matched.append((frame, paired[stamp]))

    def maximum(key):
        values = [item.get(key) for _, comparisons in matched for item in comparisons]
        values = [v for v in values if type(v) is int and v >= 0]
        return max(values) if values else None

    def new_cells(source):
        values = [frame.get("new_cells_total") for frame in target_by_source[source]]
        if (any("collection_error" in frame for frame in target_by_source[source])
                or any(type(value) is not int or value < 0 for value in values)):
            return None
        return sum(values)

    def change_frames(source):
        if new_cells(source) is None:
            return None
        return sum(frame["new_cells_total"] > 0 for frame in target_by_source[source])

    return {
        "status": "summarized", "mission_id": tracked_id, "session_id": session,
        "mission_status": mission.get("status"), "mission_error": mission.get("error"),
        "travelled_xy_m": mission.get("travelled_xy_m"), "distance_complete": mission.get("distance_complete"),
        "plan_revision": mission.get("plan_revision"),
        "requested_poll_interval_s": poll_s, "mission_samples": mission_samples, "fusion_status_counts": dict(statuses),
        "polled_states": dict(polled_states),
        "last_control_timing_process_lifetime": last_control,
        "invalid_comparisons": invalid_comparisons, "session_mismatches": session_mismatches,
        "unique_sampled_lidar_stamps": len(paired), "retained_lidar_map_change_frames": len(target_frames),
        "retained_map_change_frames_by_source": {key: change_frames(key) for key in target_by_source},
        "retained_new_cells_by_source": {key: new_cells(key) for key in target_by_source},
        "matched_change_frames_by_stamp": len(matched), "unmatched_change_frames": missing,
        "ambiguous_recorded_change_frames": ambiguous, "change_frames_without_valid_stamp": invalid_stamp,
        "unattributed_lidar_frames": unattributed, "max_shared_bins_matched": maximum("shared_bins"),
        "max_lidar_hazard_depth_ground_bins_matched": maximum("lidar_hazard_depth_ground_like_bins"),
        "max_lidar_negative_depth_ground_bins_matched": maximum("lidar_negative_depth_ground_like_bins"),
        "samples_evicted": samples_evicted, "diagnostic_frames_evicted": diag.get("frames_evicted"),
        "truncated_lidar_change_frames": sum(type(f.get("new_cells_truncated")) is int
                                             and f["new_cells_truncated"] > 0 for f in target_frames),
        "unknown_truncation_lidar_change_frames": sum(type(f.get("new_cells_truncated")) is not int
                                                      or f["new_cells_truncated"] < 0 for f in target_frames),
        "lidar_frame_collection_errors": sum("collection_error" in f for f in target_by_source["lidar"]),
        "unverifiable_lidar_frames": sum("collection_error" in f or type(f.get("new_cells_total")) is not int
                                         or f["new_cells_total"] < 0 for f in target_by_source["lidar"]),
        "limits": "Polling is not continuous. The match uses session and capture stamp; duplicates in "
                  "unrecorded frames cannot be ruled out. Shared 25 cm bins are not matching rays or "
                  "necessarily the changed cells. Frame counts exclude other missions; the map may retain "
                  "older cells. This cannot prove obstacles false or a route safe.",
    }


def record(output_dir, *, duration_s=150, poll_s=0.75, checkpoint_s=3, capture_fusion=False,
           get_json=read_local_json, now=time.monotonic, sleep=time.sleep, log=print):
    if type(capture_fusion) is not bool or not all(isinstance(n, (int, float)) and math.isfinite(n) and n > 0
               for n in (duration_s, poll_s, checkpoint_s)):
        raise ValueError("Duration and intervals must be positive finite numbers")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    while True:
        run_id = uuid.uuid4().hex
        samples_path = output_dir / f"gorev-izleme-anlik-{run_id}.json"
        mission_path = output_dir / f"gorev-izleme-gecmis-{run_id}.json"
        if not samples_path.exists() and not mission_path.exists():
            break
    log(f"ANLIK_DOSYA: {samples_path}")
    log(f"GECMIS_DOSYA: {mission_path}")
    samples = deque(maxlen=4096)
    samples_evicted = 0
    start = now()
    next_checkpoint = start
    baseline_known = False
    baseline_id = None
    tracked_id = None
    last_session_id = None
    failures = 0
    reason = "timeout"
    last_export_s = None
    last_message = None

    def checkpoint():
        nonlocal last_export_s
        try:
            export = get_json("/mission/export")
        except (OSError, ValueError, TimeoutError) as error:
            log(f"Gecmis su anda okunamadi; son basarili kayit korunuyor: {error}")
        else:
            missions = export.get("missions") if isinstance(export, dict) else None
            contains_tracked = isinstance(missions, list) and any(
                isinstance(mission, dict) and mission.get("mission_id") == tracked_id for mission in missions
            )
            if not isinstance(missions, list):
                log("Gorev gecmisi beklenen bicimde degil; onceki kayit korunuyor.")
            elif tracked_id and not contains_tracked:
                log("Izlenen gorev yeni gecmiste bulunamadi; onceki kayit korunuyor.")
            else:
                atomic_json(mission_path, export)
                last_export_s = max(0.0, now() - start)
        atomic_json(samples_path, {"schema_version": 1, "tracked_mission_id": tracked_id,
                                   "last_export_elapsed_s": last_export_s,
                                   "samples_evicted": samples_evicted, "samples": list(samples)})

    try:
        while now() - start < duration_s:
            elapsed = max(0.0, now() - start)
            try:
                snapshot = get_json("/mission/snapshot")
                if not isinstance(snapshot, dict):
                    raise ValueError("Snapshot must be a JSON object")
                failures = 0
                mission = snapshot.get("mission") or {}
                if not isinstance(mission, dict):
                    raise ValueError("Mission must be a JSON object or null")
                mission_id, closed = mission.get("mission_id"), mission.get("closed") is True
                session_id = snapshot.get("session_id")
                if tracked_id and last_session_id and session_id and session_id != last_session_id:
                    reason = "session_changed"
                if session_id:
                    last_session_id = session_id
                if not baseline_known:
                    if capture_fusion:
                        if snapshot.get("fusion_shadow_enabled") is not True:
                            reason = "fusion_shadow_disabled"
                            log("ON_KONTROL_BASARISIZ: nav_service --fusion-shadow ile baslatilmali; "
                                "bu arac hedef gondermedi.")
                            break
                        speed, wheels = snapshot.get("speed_estimate_m_s"), snapshot.get("wheel_command_m_s")
                        stopped = (type(speed) in (int, float) and math.isfinite(speed) and 0 <= speed <= 0.02
                                   and isinstance(wheels, dict)
                                   and all(type(wheels.get(k)) in (int, float) and math.isfinite(wheels[k])
                                           and abs(wheels[k]) <= 1e-9 for k in ("FL", "FR", "BL", "BR")))
                        if (snapshot.get("state") not in ("idle", "new_session_requires_goal")
                                or snapshot.get("pose_fresh") is not True
                                or snapshot.get("capture_clock_advancing") is not True
                                or not isinstance(session_id, str) or not session_id or not stopped
                                or (bool(mission) and not closed)):
                            reason = "preflight_unsuitable"
                            log("ON_KONTROL_BASARISIZ: rover bos, poz taze, saat ilerliyor, "
                                "hiz <= 0.02 m/s ve teker komutlari sifir olmali; bu arac hedef gondermedi.")
                            break
                        initial_export = get_json("/mission/export")
                        initial_diag = initial_export.get("obstacle_diagnostics") if isinstance(initial_export, dict) else None
                        if not isinstance(initial_diag, dict) or initial_diag.get("enabled") is not True:
                            reason = "obstacle_diagnostics_disabled"
                            log("ON_KONTROL_BASARISIZ: nav_service --obstacle-diagnostics ile baslatilmali; "
                                "bu arac hedef gondermedi.")
                            break
                    baseline_id = mission_id if closed else None
                    baseline_known = True
                    log("KAYIT_HAZIR: izleme basladi; bu arac hareket komutu gondermez.")
                if mission_id and (not closed or mission_id != baseline_id):
                    tracked_id = mission_id
                samples_evicted += int(len(samples) == samples.maxlen)
                sample = {"elapsed_s": elapsed, "snapshot": snapshot}
                if capture_fusion:
                    sample["fusion_request_elapsed_s"] = max(0.0, now() - start)
                    try:
                        shadow = get_json("/dashboard/fusion-shadow")
                        if not isinstance(shadow, dict) or not isinstance(shadow.get("status"), str):
                            raise ValueError("Fusion response must include a status")
                        sample["fusion_shadow"] = shadow
                    except (OSError, ValueError, TimeoutError) as error:
                        sample["fusion_shadow_error"] = str(error)[:256]
                    sample["fusion_response_elapsed_s"] = max(0.0, now() - start)
                samples.append(sample)
                message = (snapshot.get("state"), mission_id, mission.get("error"))
                if message != last_message:
                    log(f"{elapsed:.1f} s | durum={message[0]} | gorev={message[1]} | hata={message[2]}")
                    last_message = message
                if reason == "timeout" and tracked_id and mission_id == tracked_id and closed:
                    reason = "mission_finished"
            except (OSError, ValueError, TimeoutError) as error:
                failures += 1
                samples_evicted += int(len(samples) == samples.maxlen)
                samples.append({"elapsed_s": elapsed, "error": str(error)})
                log(f"Durum okunamadi ({failures}/3): {error}")
                if failures >= 3:
                    reason = "service_unavailable"
            if now() >= next_checkpoint or reason != "timeout":
                checkpoint()
                next_checkpoint = now() + checkpoint_s
            if reason != "timeout":
                break
            sleep(min(poll_s, max(0.0, duration_s - (now() - start))))
    except KeyboardInterrupt:
        reason = "interrupted"
    finally:
        checkpoint()
    log(f"IZLEME_BITTI: {reason}; bu arac hedef veya dur komutu gondermedi.")
    log(f"ANLIK_DOSYA: {samples_path}")
    if mission_path.exists():
        log(f"GECMIS_DOSYA: {mission_path} (son basarili kayit)")
    else:
        log("GECMIS_DOSYA: basarili bir gorev gecmisi kaydi alinamadi.")
    if capture_fusion:
        try:
            with mission_path.open(encoding="utf-8-sig") as handle:
                export = json.load(handle)
            summary = summarize_fusion(samples, export, tracked_id, samples_evicted=samples_evicted, poll_s=poll_s)
        except (OSError, ValueError, TypeError) as error:
            summary = {"status": "unavailable", "reason": str(error)[:256]}
        log("MARS_FUSION_RUN: " + json.dumps(summary, ensure_ascii=False, allow_nan=False))
    return {"reason": reason, "samples": samples_path, "mission": mission_path}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=150)
    parser.add_argument("--output-dir", type=Path, default=Path("Saved/Mars"))
    parser.add_argument("--fusion-shadow", action="store_true",
                        help="also record read-only sampled LiDAR/depth comparisons")
    parser.add_argument("--poll-seconds", type=float, default=0.75,
                        help="poll interval in seconds (0.5 to 5)")
    args = parser.parse_args()
    if not 1 <= args.seconds <= 900:
        parser.error("--seconds must be in 1..900")
    if not 0.5 <= args.poll_seconds <= 5:
        parser.error("--poll-seconds must be in 0.5..5")
    record(args.output_dir, duration_s=args.seconds, poll_s=args.poll_seconds, capture_fusion=args.fusion_shadow)


if __name__ == "__main__":
    main()
