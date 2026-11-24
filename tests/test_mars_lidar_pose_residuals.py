"""Counterfactual point reprojection for recorded obstacle evidence."""

import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mars_rover.planning import TerrainMap  # noqa: E402
from mars_rover.sensors import pose_from_telemetry  # noqa: E402
from tools import analyze_lidar_pose_residuals as tool  # noqa: E402

analyze = tool.analyze

STAMP = 1_700_000_000_100_000_000


def pose(stamp=STAMP, pitch=0.0):
    return {"frame_id": "42", "stamp_ns": str(stamp), "x": -500.0, "y": 500.0, "z": 0.0,
            "roll": 0.0, "pitch": pitch, "yaw": 180.0}


def log_line(capture):
    return "[date][frame]LogTemp: MARS_LIDAR_POSE: " + json.dumps(capture) + "\n"


def fixture():
    grid = TerrainMap(np.zeros((12, 12)), 1)
    grid.manifest_sha256 = "terrain-hash"
    used = pose_from_telemetry({**pose(), "t_ns": str(STAMP)}).matrix.tolist()
    frame = {"source": "lidar", "frame_id": 42, "stamp_ns": str(STAMP), "session_id": "session",
             "mission_id": "mission", "world_from_body": used, "new_cells_total": 1,
             "new_cells_truncated": 0, "new_cells": [{"cell_row_col": [5, 9], "hazard_points": 40,
                                                         "sample_world_m": [9.0, 5.0, 0.2],
                                                         "sample_residual_m": 0.2}]}
    report = {"start_session_id": "session", "mission_export": {"session_id": "session",
              "terrain_manifest_sha256": "terrain-hash", "missions": [{"session_id": "session",
                                                                          "mission_id": "mission"}],
              "obstacle_diagnostics": {"enabled": True, "frames_evicted": 0, "frames": [frame]}}}
    return grid, report


class TestPoseResidualAnalysis(unittest.TestCase):
    def test_reprojects_recorded_point_and_keeps_inputs_unchanged(self):
        grid, report = fixture()
        before, heights = copy.deepcopy(report), grid.heights.copy()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Unreal.log"
            path.write_text(log_line(pose(pitch=-3)), encoding="utf-8")
            contents = path.read_bytes()
            result = analyze(report, path, grid)
            self.assertEqual(path.read_bytes(), contents)
        self.assertEqual(report, before)
        np.testing.assert_array_equal(grid.heights, heights)
        self.assertEqual(result["lidar_frames_matched"], 1)
        self.assertEqual(result["representative_samples"], 1)
        sample = result["frames"][0]["samples"][0]
        self.assertAlmostEqual(sample["recorded_residual_m"], 0.2)
        self.assertLess(abs(sample["request_pose_residual_m"]), 0.15)
        self.assertFalse(sample["request_pose_sample_exceeds_threshold"])
        self.assertAlmostEqual(result["frames"][0]["used_vs_request_orientation_deg"], 3, places=6)

    def test_duplicate_and_missing_log_matches_are_not_used(self):
        grid, report = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Unreal.log"
            path.write_text(log_line(pose()) * 2, encoding="utf-8")
            result = analyze(report, path, grid)
            self.assertEqual(result["lidar_frames_ambiguous_log"], [42])
            self.assertEqual(result["lidar_frames_matched"], 0)
            path.write_text(log_line(pose(STAMP + 2_000)), encoding="utf-8")
            result = analyze(report, path, grid)
        self.assertEqual(result["lidar_frames_missing_log"], [42])

    def test_utf16_timestamp_tolerance_and_different_missions(self):
        grid, report = fixture()
        other = copy.deepcopy(report["mission_export"]["obstacle_diagnostics"]["frames"][0])
        other["mission_id"] = "previous-mission"
        report["mission_export"]["obstacle_diagnostics"]["frames"].append(other)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Unreal.log"
            path.write_bytes(log_line(pose(STAMP + 256)).encode("utf-16"))
            result = analyze(report, path, grid)
        self.assertEqual(result["lidar_frames_recorded"], 1)
        self.assertEqual(result["lidar_frames_matched"], 1)
        self.assertTrue(result["frames"][0]["samples"][0]["request_pose_sample_exceeds_threshold"])

    def test_mismatched_terrain_or_recorded_residual_is_rejected(self):
        grid, report = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Unreal.log"
            path.write_text(log_line(pose()), encoding="utf-8")
            report["mission_export"]["terrain_manifest_sha256"] = "different"
            with self.assertRaisesRegex(ValueError, "manifest"):
                analyze(report, path, grid)
            report["mission_export"]["terrain_manifest_sha256"] = grid.manifest_sha256
            report["mission_export"]["obstacle_diagnostics"]["frames"][0]["new_cells"][0]["sample_residual_m"] = 0.3
            with self.assertRaisesRegex(ValueError, "residual"):
                analyze(report, path, grid)

    def test_reported_mission_is_identified_from_observed_snapshots(self):
        grid, report = fixture()
        report["snapshots"] = [{"session_id": "session", "mission": {"mission_id": "mission"}}]
        report["mission_export"]["missions"].append({"session_id": "session", "mission_id": "later"})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Unreal.log"
            path.write_text(log_line(pose()), encoding="utf-8")
            self.assertEqual(analyze(report, path, grid)["mission_id"], "mission")
            report["snapshots"].append({"session_id": "session", "mission": {"mission_id": "later"}})
            with self.assertRaisesRegex(ValueError, "Multiple missions"):
                analyze(report, path, grid)

    def test_cli_writes_complete_results_and_prints_compact_summary(self):
        grid, report = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logfile, reportfile = root / "Unreal.log", root / "turn.json"
            logfile.write_text(log_line(pose(pitch=-3)), encoding="utf-8")
            reportfile.write_text(json.dumps(report), encoding="utf-8")
            stdout = io.StringIO()
            with (patch.object(tool, "ROOT", root), patch.object(tool.TerrainMap, "from_bundle", return_value=grid),
                  patch.object(sys, "argv", ["tool", str(reportfile), "--log", str(logfile)]),
                  redirect_stdout(stdout)):
                tool.main()
            files = list((root / "Saved/Mars").glob("lidar-poz-karsilastirma-*.json"))
            self.assertEqual(len(files), 1)
            result = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(result["representative_samples"], 1)
        self.assertEqual(len(result["frames"][0]["samples"]), 1)
        self.assertIn("MARS_LIDAR_RESIDUAL:", stdout.getvalue())
        self.assertNotIn('"samples":', stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
