"""The readiness inspection must only perform local GET requests."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import check_mars_readiness as probe  # noqa: E402


def snapshot():
    return {"session_id": "session-a", "state": "idle", "pose_fresh": False, "pose_age_s": 0.5,
            "capture_clock_advancing": False, "position_source": "simulation telemetry",
            "depth_source": "ground_truth", "observer_error": "No fresh pose telemetry",
            "lidar_ingest_timing": {"samples": [{"frame_id": 1}, {"frame_id": 2}, {"frame_id": 3}, {"frame_id": 4}]}}


def bridge():
    return {"connected": False, "connection_id": 4, "telemetry_age_s": None,
            "telemetry_format": "unreal-tr-v1", "last_error": "connection lost"}


class TestReadOnlyReadiness(unittest.TestCase):
    def test_collects_only_snapshot_and_bridge_and_explains_preflight(self):
        calls, sleeps = [], []

        def get(path):
            calls.append(path)
            return snapshot() if path == "/mission/snapshot" else bridge()

        result = probe.collect(get=get, sleep=sleeps.append, expected_session="session-a")
        self.assertEqual(calls, ["/mission/snapshot", "bridge"] * 3)
        self.assertEqual(sleeps, [0.5, 0.5])
        self.assertEqual(result["mode"], "read_only")
        self.assertTrue(all(s["expected_session_matches"] for s in result["samples"]))
        self.assertIn("pose_not_fresh", result["samples"][0]["snapshot_check"])
        self.assertIn("capture_clock_not_advancing", result["samples"][0]["snapshot_check"])
        self.assertEqual([s["frame_id"] for s in result["samples"][0]["lidar_ingest_recent"]], [2, 3, 4])
        self.assertEqual(result["samples"][0]["bridge"]["last_error"], "connection lost")

    def test_independent_endpoint_errors_and_session_change_are_preserved(self):
        calls = []

        def get(path):
            calls.append(path)
            if path == "bridge":
                raise OSError("unavailable")
            return snapshot()

        result = probe.collect(get=get, sleep=lambda _: None, expected_session="different")
        self.assertEqual(calls, ["/mission/snapshot", "bridge"] * 3)
        self.assertTrue(all(not s["expected_session_matches"] for s in result["samples"]))
        self.assertTrue(all(s["bridge_error"] == "unavailable" for s in result["samples"]))

    def test_main_prints_json_for_optional_expected_session(self):
        stdout = io.StringIO()
        with (patch.object(sys, "argv", ["check_mars_readiness.py", "--expected-session", "abc"]),
              patch.object(probe, "collect", return_value={"mode": "read_only"}) as collect,
              redirect_stdout(stdout)):
            probe.main()
        collect.assert_called_once_with(expected_session="abc")
        data = json.loads(stdout.getvalue().split("MARS_READ_ONLY_STATUS: ", 1)[1])
        self.assertEqual(data["mode"], "read_only")


if __name__ == "__main__":
    unittest.main()
