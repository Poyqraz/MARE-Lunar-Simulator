"""Read simulator readiness three times without sending motion or stop commands."""

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.mars_lidar_turn_probe import _bridge_stationary, _get, _stationary  # noqa: E402


def _check(function, data):
    if not isinstance(data, dict):
        return "response_not_an_object"
    try:
        function(data)
        return "passed"
    except (ValueError, TypeError, KeyError) as error:
        return str(error)


def collect(*, get=_get, sleep=time.sleep, expected_session=None):
    """GET only. Snapshots and bridge status are separate requests, not atomic."""
    samples = []
    for i in range(3):
        item = {"sample": i + 1}
        try:
            snapshot = get("/mission/snapshot")
            if not isinstance(snapshot, dict):
                raise ValueError("Snapshot is not an object")
            keys = ("session_id", "state", "pose_fresh", "pose_age_s", "capture_clock_advancing",
                    "speed_estimate_m_s", "live_pose", "mission", "observer_error", "sensor_observation_error",
                    "sensor_health", "wheel_command_m_s", "control_timing", "telemetry_timing")
            item["snapshot"] = {key: snapshot.get(key) for key in keys}
            item["snapshot_check"] = _check(_stationary, snapshot)
            item["expected_session_matches"] = (
                snapshot.get("session_id") == expected_session if expected_session is not None else None
            )
            timing = snapshot.get("lidar_ingest_timing") or {}
            if not isinstance(timing, dict):
                raise ValueError("LiDAR timing is not an object")
            recent = timing.get("samples") or []
            if not isinstance(recent, list):
                raise ValueError("LiDAR timing samples are not a list")
            item["lidar_ingest_recent"] = recent[-3:]
            item["lidar_ingest_error"] = timing.get("collection_error")
        except (OSError, ValueError, TypeError, KeyError) as error:
            item["snapshot_error"] = str(error)[:500]
        try:
            bridge = get("bridge")
            if not isinstance(bridge, dict):
                raise ValueError("Bridge status is not an object")
            keys = ("connected", "connection_id", "telemetry_age_s", "telemetry_format", "telemetry_timing",
                    "last_error", "wheel_command_m_s", "telemetry_unreal")
            item["bridge"] = {key: bridge.get(key) for key in keys}
            item["bridge_check"] = _check(_bridge_stationary, bridge)
        except (OSError, ValueError, TypeError, KeyError) as error:
            item["bridge_error"] = str(error)[:500]
        samples.append(item)
        if i < 2:
            sleep(0.5)
    return {"mode": "read_only", "expected_session": expected_session, "samples": samples,
            "limits": "Snapshot and bridge are separate GET requests. These checks do not evaluate "
                      "the map, pose log or an entire future turn; no goal or stop is sent."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-session", help="Session ID shown by the tick-alignment experiment")
    args = parser.parse_args()
    result = collect(expected_session=args.expected_session)
    print("MARS_READ_ONLY_STATUS:", json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
