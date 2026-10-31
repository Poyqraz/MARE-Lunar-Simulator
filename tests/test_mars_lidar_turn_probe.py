"""Controlled-turn preflight and guaranteed stop attempts, using no network."""

import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import mars_lidar_turn_probe as probe  # noqa: E402


STAMP = 1_700_000_000_000_000_000


def snapshot(*, state="idle", mission=None, heading=-math.pi / 2, stamp=STAMP):
    sensor = {"stamp_ns": str(stamp - 100_000_000), "received_age_s": 0.05, "valid_inside_points": 100}
    return {"position_source": "simulation telemetry", "depth_source": "ground_truth", "state": state,
            "mission": mission, "pose_fresh": True, "capture_clock_advancing": True,
            "speed_estimate_m_s": 0.001, "wheel_command_m_s": dict.fromkeys(("FL", "FR", "BL", "BR"), 0.0),
            "live_pose": {"stamp_ns": str(stamp), "position_m": [10.0, 10.0, 1.0], "heading_rad": heading},
            "sensor_health": {"lidar": sensor, "ground_truth": copy.deepcopy(sensor)},
            "session_id": "session-a", "map_revision": 3}


def bridge():
    return {"connected": True, "telemetry_format": "unreal-tr-v1", "telemetry_age_s": 0.01,
            "wheel_command_m_s": dict.fromkeys(("FL", "FR", "BL", "BR"), 0.0),
            "telemetry_unreal": {"wx": 0.0, "wy": 0.0, "wz": 0.0}}


def grid():
    return {"width": 20, "height": 20, "resolution_m": 1, "blocked": [0] * 400, "revision": 3}


class FakeRun:
    def __init__(self):
        self.clock = 0.0
        self.posts = []
        self.snapshot_count = 0
        self.analysis_count = 0
        self.goal_error = None
        self.stop_error = None
        self.analysis_error = False
        self.moving_snapshot = snapshot(heading=-math.pi / 2 + math.radians(50), stamp=STAMP + 100_000_000)

    def now(self):
        return self.clock

    def sleep(self, seconds):
        self.clock += seconds

    def get(self, path):
        if path == "bridge":
            return bridge()
        if path == "/map":
            return grid()
        if path == "/mission/export":
            return {"missions": []}
        if path == "/mission/snapshot":
            self.snapshot_count += 1
            return snapshot() if self.snapshot_count <= 2 else self.moving_snapshot
        raise AssertionError(path)

    def post(self, path, body):
        self.posts.append((path, body))
        if path == "/goal" and self.goal_error:
            raise self.goal_error
        if path == "/stop" and self.stop_error:
            raise self.stop_error
        return {"ok": True}

    def analyzer(self, path, **kwargs):
        self.analysis_count += 1
        if "start_stamp_ns" in kwargs:
            if self.analysis_error:
                raise ValueError("parse failure")
            return {"status": "matched", "matched_frames": 10}
        stamp = STAMP - 200_000_000 if self.analysis_count == 1 else STAMP - 100_000_000
        return {"status": "matched", "last_capture_stamp_ns": str(stamp)}

    def run(self):
        return probe.run("fake.log", get=self.get, post=self.post, analyzer=self.analyzer,
                         now=self.now, sleep=self.sleep)


class TestControlledTurn(unittest.TestCase):
    def test_reaches_angle_limit_then_sends_stop_and_reports(self):
        sim = FakeRun()
        result = sim.run()
        self.assertEqual(result["reason"], "turn_observed")
        self.assertTrue(result["goal_confirmed"])
        self.assertTrue(result["stop_request_succeeded"])
        self.assertEqual(result["final_status"]["wheel_command_m_s"], dict.fromkeys(("FL", "FR", "BL", "BR"), 0.0))
        self.assertEqual([p[0] for p in sim.posts], ["/goal", "/stop"])
        self.assertAlmostEqual(sim.posts[0][1]["x"], 10.0)
        self.assertAlmostEqual(sim.posts[0][1]["y"], 12.0)
        self.assertEqual(result["pose_comparison"]["matched_frames"], 10)

    def test_preflight_failures_never_send_a_goal_or_stop(self):
        for changed in ("active", "stale", "blocked", "no_log", "wrong_format", "bridge_wheel"):
            sim = FakeRun()
            original_get, original_analyzer = sim.get, sim.analyzer

            def get(path):
                result = copy.deepcopy(original_get(path))
                if changed == "active" and path == "/mission/snapshot":
                    result["mission"] = {"closed": False}
                if changed == "stale" and path == "/mission/snapshot":
                    result["sensor_health"]["lidar"]["stamp_ns"] = str(STAMP - 500_000_000)
                if changed == "blocked" and path == "/map":
                    result["blocked"][11 * 20 + 10] = 1
                if changed == "wrong_format" and path == "bridge":
                    result["telemetry_format"] = "json"
                if changed == "bridge_wheel" and path == "bridge":
                    result["wheel_command_m_s"]["FL"] = 0.1
                return result

            def analyzer(path, **kwargs):
                result = original_analyzer(path, **kwargs)
                return {"status": "no_matched_frames"} if changed == "no_log" else result

            with self.subTest(changed=changed), self.assertRaises(ValueError):
                probe.run("fake.log", get=get, post=sim.post, analyzer=analyzer, now=sim.now, sleep=sim.sleep)
            self.assertEqual(sim.posts, [])

    def test_sensor_preflight_reports_the_specific_rejection_without_commands(self):
        cases = {
            "capture_stale": ({"capture_stale": True}, "capture_stale"),
            "arrival": ({"received_age_s": 0.351}, "received_age_invalid_or_over_0.35s"),
            "count": ({"valid_inside_points": 19}, "valid_points_under_20_or_missing"),
            "older": ({"stamp_ns": str(STAMP - 350_000_001)}, "capture_older_than_0.35s"),
            "future": ({"stamp_ns": str(STAMP + 1025)}, "sensor_ahead_of_pose"),
            "missing_stamp": ({"stamp_ns": None}, "sensor_zamani_gecersiz"),
        }
        for name, (override, message) in cases.items():
            for bad_snapshot in (1, 2):
                sim = FakeRun()
                original_get = sim.get

                def get(path):
                    result = copy.deepcopy(original_get(path))
                    if path == "/mission/snapshot" and sim.snapshot_count == bad_snapshot:
                        result["sensor_health"]["lidar"].update(override)
                    return result

                with self.subTest(case=name, snapshot=bad_snapshot), self.assertRaisesRegex(ValueError, message):
                    probe.run("fake.log", get=get, post=sim.post, analyzer=sim.analyzer, now=sim.now, sleep=sim.sleep)
                self.assertEqual(sim.posts, [])

    def test_state_preflight_explains_the_failure_and_snapshot_without_commands(self):
        cases = {
            "state": ({"state": "disconnected"}, "state_not_idle"),
            "pose": ({"pose_fresh": False}, "pose_not_fresh"),
            "clock": ({"capture_clock_advancing": False}, "capture_clock_not_advancing"),
        }
        for case, (override, expected) in cases.items():
            for bad_snapshot in (1, 2):
                sim = FakeRun()
                original_get = sim.get

                def get(path):
                    result = copy.deepcopy(original_get(path))
                    if path == "/mission/snapshot" and sim.snapshot_count == bad_snapshot:
                        result.update(override, pose_age_s=0.45, observer_error="test diagnostic")
                    return result

                with self.subTest(case=case, snapshot=bad_snapshot):
                    with self.assertRaisesRegex(ValueError, expected) as raised:
                        probe.run("fake.log", get=get, post=sim.post, analyzer=sim.analyzer,
                                  now=sim.now, sleep=sim.sleep)
                    self.assertIn(f"on_kontrol_ornegi={bad_snapshot}", str(raised.exception))
                    self.assertIn("session_id='session-a'", str(raised.exception))
                    self.assertIn("pose_age_s=0.45", str(raised.exception))
                    self.assertIn("observer_error='test diagnostic'", str(raised.exception))
                    self.assertEqual(sim.posts, [])

    def test_new_session_idle_state_remains_accepted(self):
        data = snapshot(state="new_session_requires_goal")
        probe._stationary(data)

    def test_expected_alignment_session_must_match_both_preflight_samples(self):
        for changed_snapshot in (1, 2):
            sim = FakeRun()
            original_get = sim.get

            def get(path):
                result = copy.deepcopy(original_get(path))
                if path == "/mission/snapshot" and sim.snapshot_count == changed_snapshot:
                    result["session_id"] = "different"
                return result

            with self.subTest(snapshot=changed_snapshot), self.assertRaisesRegex(ValueError, "Hizalama oturumu degisti"):
                probe.run("fake.log", get=get, post=sim.post, analyzer=sim.analyzer,
                          now=sim.now, sleep=sim.sleep, expected_session="session-a")
            self.assertEqual(sim.posts, [])

        sim = FakeRun()
        result = probe.run("fake.log", get=sim.get, post=sim.post, analyzer=sim.analyzer,
                           now=sim.now, sleep=sim.sleep, expected_session="session-a")
        self.assertEqual(result["expected_session_id"], "session-a")
        self.assertEqual([p[0] for p in sim.posts], ["/goal", "/stop"])

    def test_session_change_during_turn_attempts_stop(self):
        sim = FakeRun()
        sim.moving_snapshot["session_id"] = "different"
        result = probe.run("fake.log", get=sim.get, post=sim.post, analyzer=sim.analyzer,
                           now=sim.now, sleep=sim.sleep, expected_session="session-a")
        self.assertEqual(result["reason"], "session_changed")
        self.assertEqual([p[0] for p in sim.posts], ["/goal", "/stop"])

    def test_sensor_freshness_boundaries_are_unchanged(self):
        data = snapshot()
        for sensor in data["sensor_health"].values():
            sensor.update(stamp_ns=str(STAMP - 350_000_000), received_age_s=0.35, valid_inside_points=20)
        probe._stationary(data)
        for sensor in data["sensor_health"].values():
            sensor["stamp_ns"] = str(STAMP + 1024)
        probe._stationary(data)

    def test_stop_is_attempted_even_if_goal_request_times_out(self):
        sim = FakeRun()
        sim.goal_error = TimeoutError("goal response timed out")
        result = sim.run()
        self.assertEqual([p[0] for p in sim.posts], ["/goal", "/stop"])
        self.assertEqual(result["reason"], "request_error")
        self.assertFalse(result["goal_confirmed"])
        self.assertTrue(result["stop_request_succeeded"])
        self.assertIn("timed out", result["error"])

    def test_stop_failure_is_reported_and_analysis_failure_cannot_skip_stop(self):
        sim = FakeRun()
        sim.stop_error = TimeoutError("no reply")
        sim.analysis_error = True
        result = sim.run()
        self.assertEqual([p[0] for p in sim.posts], ["/goal", "/stop"])
        self.assertFalse(result["stop_request_succeeded"])
        self.assertIn("Stop istegi basarisiz", result["error"])
        self.assertEqual(result["pose_comparison"]["status"], "analysis_error")

    def test_stale_tag_log_cannot_start_motion(self):
        sim = FakeRun()

        def analyzer(path, **kwargs):
            return {"status": "matched", "last_capture_stamp_ns": str(STAMP - 100_000_000)}

        with self.assertRaisesRegex(ValueError, "logu ilerlemiyor"):
            probe.run("fake.log", get=sim.get, post=sim.post, analyzer=analyzer, now=sim.now, sleep=sim.sleep)
        self.assertEqual(sim.posts, [])

    def test_pose_becoming_stale_during_motion_attempts_stop(self):
        sim = FakeRun()
        sim.moving_snapshot["pose_fresh"] = False
        result = sim.run()
        self.assertEqual(result["reason"], "pose_stale")
        self.assertEqual([p[0] for p in sim.posts], ["/goal", "/stop"])

    def test_back_and_forth_motion_counts_toward_translation_limit(self):
        sim = FakeRun()
        original_get = sim.get
        positions = iter((10.12, 10.0))

        def get(path):
            if path == "/mission/snapshot" and sim.snapshot_count >= 2:
                data = snapshot(heading=-math.pi / 2, stamp=STAMP + 100_000_000)
                data["live_pose"]["position_m"][0] = next(positions, 10.0)
                sim.snapshot_count += 1
                return data
            return original_get(path)

        result = probe.run("fake.log", get=get, post=sim.post, analyzer=sim.analyzer,
                           now=sim.now, sleep=sim.sleep)
        self.assertEqual(result["reason"], "translation_limit")
        self.assertAlmostEqual(result["sampled_path_m"], 0.24)
        self.assertEqual([p[0] for p in sim.posts], ["/goal", "/stop"])

    def test_timeout_and_translation_limit_both_attempt_stop(self):
        timeout = FakeRun()
        timeout.moving_snapshot = snapshot(heading=-math.pi / 2, stamp=STAMP + 100_000_000)
        result = timeout.run()
        self.assertEqual(result["reason"], "timeout")
        self.assertEqual([p[0] for p in timeout.posts], ["/goal", "/stop"])

        moved = FakeRun()
        moved.moving_snapshot = snapshot(heading=-math.pi / 2, stamp=STAMP + 100_000_000)
        moved.moving_snapshot["live_pose"]["position_m"][0] += 0.21
        result = moved.run()
        self.assertEqual(result["reason"], "translation_limit")
        self.assertEqual([p[0] for p in moved.posts], ["/goal", "/stop"])

    def test_keyboard_interrupt_after_goal_still_attempts_stop(self):
        sim = FakeRun()
        sim.goal_error = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            sim.run()
        self.assertEqual([p[0] for p in sim.posts], ["/goal", "/stop"])

    def test_segment_rejects_diagonal_corner_cut(self):
        data = grid()
        data["blocked"][10 * 20 + 11] = 1
        self.assertFalse(probe._segment_is_open(data, (10, 10), (11, 11)))

    def test_local_http_integration_sends_only_goal_then_stop(self):
        sim = FakeRun()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                path = "bridge" if self.path == "/bridge" else self.path
                payload = json.dumps(sim.get(path)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                payload = json.dumps(sim.post(self.path, body)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with patch.object(probe, "BASE", base), patch.object(probe, "BRIDGE", base + "/bridge"):
                result = probe.run("fake.log", analyzer=sim.analyzer, now=sim.now, sleep=sim.sleep)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(result["reason"], "turn_observed")
        self.assertEqual([p[0] for p in sim.posts], ["/goal", "/stop"])

    def test_turn_and_real_log_analyzer_use_only_the_turn_stamp_window(self):
        sim = FakeRun()

        def append_pair(path, stamp):
            telemetry = ('LogBlueprintUserMessages: [Leo_Raph_C_0] '
                         '{"time": 1,0, "x" : -100,1, "y": 100,1, "z": 100, '
                         '"roll": 0, "pitch": 0, "yaw": 180, "vx": 0, "vy": 0, "vz": 0, '
                         '"wx": 0, "wy": 0, "wz": 0, "t_ns": "' + str(stamp) + '"}')
            capture = {"frame_id": "42", "stamp_ns": str(stamp), "x": -100.1, "y": 100.1, "z": 100,
                       "roll": 0, "pitch": 1.5, "yaw": 180}
            with path.open("a", encoding="utf-8") as stream:
                stream.write(telemetry + "\nLogTemp: MARS_LIDAR_POSE: " + json.dumps(capture) + "\n")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Unreal.log"
            append_pair(path, STAMP - 200_000_000)
            sleeps = []

            def sleep(seconds):
                sleeps.append(seconds)
                sim.sleep(seconds)
                if len(sleeps) == 1:
                    append_pair(path, STAMP - 100_000_000)
                elif len(sleeps) == 2:
                    append_pair(path, STAMP + 100_000_000)

            result = probe.run(path, get=sim.get, post=sim.post, now=sim.now, sleep=sleep)
        self.assertEqual(result["reason"], "turn_observed")
        self.assertEqual(result["pose_comparison"]["matched_frames"], 1)
        self.assertEqual(result["pose_comparison"]["first_capture_stamp_ns"], str(STAMP + 100_000_000))


if __name__ == "__main__":
    unittest.main()
