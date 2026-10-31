"""Periodically record local simulation mission diagnostics; sends no commands."""

import argparse
from collections import deque
import json
import math
import os
from pathlib import Path
import tempfile
import time
import urllib.request
import uuid


def read_local_json(path):
    if path not in ("/mission/snapshot", "/mission/export"):
        raise ValueError("Recorder is restricted to read-only mission endpoints")
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


def record(output_dir, *, duration_s=150, poll_s=0.75, checkpoint_s=3,
           get_json=read_local_json, now=time.monotonic, sleep=time.sleep, log=print):
    if not all(isinstance(n, (int, float)) and math.isfinite(n) and n > 0
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
                    baseline_id = mission_id if closed else None
                    baseline_known = True
                    log("KAYIT_HAZIR: izleme basladi; bu arac hareket komutu gondermez.")
                if mission_id and (not closed or mission_id != baseline_id):
                    tracked_id = mission_id
                samples_evicted += int(len(samples) == samples.maxlen)
                samples.append({"elapsed_s": elapsed, "snapshot": snapshot})
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
    return {"reason": reason, "samples": samples_path, "mission": mission_path}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=150)
    parser.add_argument("--output-dir", type=Path, default=Path("Saved/Mars"))
    args = parser.parse_args()
    if not 1 <= args.seconds <= 900:
        parser.error("--seconds must be in 1..900")
    record(args.output_dir, duration_s=args.seconds)


if __name__ == "__main__":
    main()
