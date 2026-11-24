"""Replay selected LiDAR obstacle samples with their logged request-time pose.

Read-only with respect to Unreal, the mission report, the log, and the map.
The result is a counterfactual: the later GPU render pose is not measured and
one recorded point per newly occupied cell cannot establish that a cell is
clear. This tool does not send commands or alter the navigation map.
"""

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import sys
import uuid

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mars_rover.planning import TerrainMap  # noqa: E402
from mars_rover.sensors import CAPTURE_CLOCK_TOLERANCE_NS, pose_from_telemetry, transform_matrix  # noqa: E402


def _diagnostic_frames(report):
    export = report.get("mission_export") or {}
    session = report.get("start_session_id")
    diag = export.get("obstacle_diagnostics") or {}
    if not session or export.get("session_id") != session or diag.get("enabled") is not True:
        raise ValueError("Report session or enabled obstacle diagnostics are missing")
    missions = [m for m in export.get("missions", []) if m.get("session_id") == session and m.get("mission_id")]
    observed_ids = {(s.get("mission") or {}).get("mission_id") for s in report.get("snapshots", [])
                    if s.get("session_id") == session and isinstance(s.get("mission"), dict)} - {None}
    if len(observed_ids) > 1:
        raise ValueError("Multiple missions appeared during the controlled turn")
    candidates = [m for m in missions if m["mission_id"] in observed_ids] if observed_ids else missions
    if len(candidates) != 1:
        raise ValueError("The controlled-turn mission is missing or ambiguous")
    mission_id = candidates[0]["mission_id"]
    if report.get("goal_m") is not None and list(report["goal_m"]) != candidates[0].get("goal"):
        raise ValueError("Controlled-turn goal disagrees with the exported mission")
    frames = [f for f in diag.get("frames", []) if f.get("source") == "lidar"
              and f.get("session_id") == session and f.get("mission_id") == mission_id]
    return export, diag, mission_id, frames


def _read_request_poses(log_path, frames):
    """Scan the log without rewriting it or requiring its whole contents in memory."""
    wanted = defaultdict(list)
    for index, frame in enumerate(frames):
        wanted[int(frame["frame_id"])].append((int(frame["stamp_ns"]), index))
    matches = defaultdict(list)
    with Path(log_path).open("rb") as raw:
        prefix = raw.read(3)
    encoding = "utf-16" if prefix.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    with Path(log_path).open("r", encoding=encoding, errors="replace") as stream:
        for line in stream:
            if "LogTemp: MARS_LIDAR_POSE: " not in line:
                continue
            try:
                capture, _ = json.JSONDecoder().raw_decode(line.split("MARS_LIDAR_POSE: ", 1)[1])
                frame_id, stamp = int(capture["frame_id"]), int(capture["stamp_ns"])
                for wanted_stamp, index in wanted.get(frame_id, ()):
                    if abs(stamp - wanted_stamp) <= CAPTURE_CLOCK_TOLERANCE_NS:
                        pose = pose_from_telemetry({**capture, "t_ns": str(stamp)})
                        matches[index].append(pose.matrix)
            except (ValueError, TypeError, KeyError):
                continue
    return matches


def analyze(report, log_path, grid):
    export, diag, mission_id, frames = _diagnostic_frames(report)
    if not grid.manifest_sha256 or export.get("terrain_manifest_sha256") != grid.manifest_sha256:
        raise ValueError("Terrain manifest differs from the recorded mission")
    matches = _read_request_poses(log_path, frames)
    results, unmatched, ambiguous = [], [], []
    threshold = grid.limits.obstacle_height_m
    for index, frame in enumerate(frames):
        candidates = matches.get(index, [])
        if not candidates:
            unmatched.append(int(frame["frame_id"]))
            continue
        if len(candidates) != 1:
            ambiguous.append(int(frame["frame_id"]))
            continue
        used = transform_matrix(frame["world_from_body"])
        request = transform_matrix(candidates[0])
        rotation = used[:3, :3].T @ request[:3, :3]
        cosine = (float(np.trace(rotation)) - 1) / 2
        angle = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
        samples = []
        for cell in frame.get("new_cells", []):
            original = np.asarray(cell["sample_world_m"], dtype=float)
            if original.shape != (3,) or not np.isfinite(original).all():
                raise ValueError("Recorded representative point is invalid")
            recorded_residual = float(cell["sample_residual_m"])
            recomputed = float(original[2] - grid.surface_height(original[:2]))
            if not math.isfinite(recorded_residual) or abs(recorded_residual - recomputed) > 1e-6:
                raise ValueError("Recorded residual does not match the supplied terrain")
            body_point = used[:3, :3].T @ (original - used[:3, 3])
            counterfactual = request[:3, :3] @ body_point + request[:3, 3]
            try:
                new_residual = float(counterfactual[2] - grid.surface_height(counterfactual[:2]))
                new_cell = list(grid.cell((float(counterfactual[0]), float(counterfactual[1]))))
            except ValueError:
                new_residual, new_cell = None, None
            samples.append({
                "recorded_cell_row_col": cell["cell_row_col"], "recorded_hazard_points_in_cell": cell["hazard_points"],
                "recorded_world_m": original.tolist(), "recorded_residual_m": recorded_residual,
                "request_pose_world_m": counterfactual.tolist(), "request_pose_cell_row_col": new_cell,
                "request_pose_residual_m": new_residual,
                "request_pose_sample_exceeds_threshold": None if new_residual is None else abs(new_residual) > threshold,
            })
        results.append({
            "frame_id": int(frame["frame_id"]), "stamp_ns": str(frame["stamp_ns"]),
            "original_new_cells_total": frame.get("new_cells_total"),
            "original_new_cells_truncated": frame.get("new_cells_truncated"),
            "used_vs_request_translation_m": float(np.linalg.norm(request[:3, 3] - used[:3, 3])),
            "used_vs_request_orientation_deg": angle,
            "recorded_representative_samples": len(samples),
            "counterfactual_samples_inside_threshold": sum(s["request_pose_sample_exceeds_threshold"] is False for s in samples),
            "counterfactual_samples_outside_threshold": sum(s["request_pose_sample_exceeds_threshold"] is True for s in samples),
            "counterfactual_samples_outside_map": sum(s["request_pose_sample_exceeds_threshold"] is None for s in samples),
            "samples": samples,
        })
    return {
        "session_id": export["session_id"], "mission_id": mission_id,
        "terrain_manifest_sha256": grid.manifest_sha256, "obstacle_threshold_m": threshold,
        "diagnostic_frames_evicted": diag.get("frames_evicted"), "lidar_frames_recorded": len(frames),
        "lidar_frames_matched": len(results), "lidar_frames_missing_log": unmatched,
        "lidar_frames_ambiguous_log": ambiguous,
        "representative_samples": sum(f["recorded_representative_samples"] for f in results),
        "counterfactual_samples_inside_threshold": sum(f["counterfactual_samples_inside_threshold"] for f in results),
        "counterfactual_samples_outside_threshold": sum(f["counterfactual_samples_outside_threshold"] for f in results),
        "counterfactual_samples_outside_map": sum(f["counterfactual_samples_outside_map"] for f in results),
        "frames": results,
        "limits": "Only the recorded first representative sample per newly occupied cell is reprojected, "
                  "assuming the point's body-relative coordinates are unchanged. The GPU render-time and "
                  "moving sensor-mount poses are not measured; changing a sample's classification does not "
                  "prove a cell is clear, remove obstacles, or reproduce a complete map.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="lidar-donus-*.json from the controlled-turn tool")
    parser.add_argument("--log", type=Path, default=ROOT / "Saved/Logs/Moon_Simulator.log")
    parser.add_argument("--manifest", type=Path, default=ROOT / "Content/Mars/Jezero/manifest.json")
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8-sig"))
        result = analyze(report, args.log, TerrainMap.from_bundle(args.manifest))
        output = ROOT / "Saved/Mars" / f"lidar-poz-karsilastirma-{uuid.uuid4().hex}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"ANALIZ_BASARISIZ: {error}\n")
    summary = {k: v for k, v in result.items() if k != "frames"}
    summary["frames"] = [{k: v for k, v in frame.items() if k != "samples"} for frame in result["frames"]]
    print("MARS_LIDAR_RESIDUAL:", json.dumps(summary, ensure_ascii=False, allow_nan=False))
    print("KAYIT:", output)
    if not result["lidar_frames_matched"]:
        parser.exit(2, "Eslesen LiDAR istegi bulunamadi; eski Unreal logunu koruyun.\n")


if __name__ == "__main__":
    main()
