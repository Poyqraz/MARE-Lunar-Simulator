"""Compare opt-in LiDAR request poses with same-stamp rover Blueprint telemetry.

This reads a bounded tail of a local Unreal log; it never contacts the rover.
The LiDAR pose is sampled on the game thread at the GPU capture request, not
the later rendered image. Matching timestamps do not certify either sensor.
"""

import argparse
from bisect import bisect_left
from collections import defaultdict
import json
import math
from pathlib import Path
import re
import statistics
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mars_rover.bridge import TurkishRoverTelemetryStream  # noqa: E402
from mars_rover.sensors import CAPTURE_CLOCK_TOLERANCE_NS, pose_from_telemetry  # noqa: E402

_TELEMETRY_STAMP = re.compile(r'"t_ns"\s*:\s*"([0-9]{1,19})"')


def _capture_pose(capture):
    return pose_from_telemetry({**capture, "t_ns": capture["stamp_ns"]})


def _tail_lines(path, max_bytes=16 * 1024 * 1024):
    with Path(path).open("rb") as stream:
        prefix = stream.read(3)
        encoding = "utf-16-le" if prefix.startswith(b"\xff\xfe") else (
            "utf-16-be" if prefix.startswith(b"\xfe\xff") else "utf-8-sig"
        )
        stream.seek(0, 2)
        size = stream.tell()
        offset = max(0, size - max_bytes)
        if encoding.startswith("utf-16"):
            offset -= offset % 2
        stream.seek(offset)
        data = stream.read(max_bytes + 1)
    text = data.decode(encoding, errors="replace")
    if offset:
        _, separator, text = text.partition("\n")
        if not separator:
            return [], True
    return text.lstrip("\ufeff").splitlines(), bool(offset)


def _parse(lines):
    telemetry = defaultdict(list)
    captures, rejected_telemetry, rejected_captures = [], 0, 0
    for line in lines:
        if "LogTemp: MARS_LIDAR_POSE: " in line:
            try:
                raw = line.split("MARS_LIDAR_POSE: ", 1)[1]
                capture, _ = json.JSONDecoder().raw_decode(raw)
                if not isinstance(capture, dict) or not str(capture["stamp_ns"]).isascii():
                    raise ValueError("Invalid capture")
                int(capture["frame_id"])
                _capture_pose(capture)
                captures.append(capture)
            except (ValueError, TypeError, KeyError):
                rejected_captures += 1
        elif "LogBlueprintUserMessages:" in line and "[Leo_Raph" in line:
            start, end = line.find("{"), line.rfind("}")
            if start < 0 or end < start:
                continue
            try:
                payload = line[start : end + 1]
                match = _TELEMETRY_STAMP.search(payload)
                if match is None:
                    raise ValueError("Telemetry timestamp missing")
                telemetry[int(match.group(1))].append(payload)
            except (ValueError, TypeError):
                rejected_telemetry += 1
    return telemetry, captures, rejected_telemetry, rejected_captures


def _metrics(capture, telemetry):
    request = _capture_pose(capture).matrix
    pose = pose_from_telemetry(telemetry).matrix
    translation = request[:3, 3] - pose[:3, 3]
    cosine = (float(np.trace(request[:3, :3].T @ pose[:3, :3])) - 1) / 2
    up_cosine = float(np.dot(request[:3, 2], pose[:3, 2]))
    angle = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
    tilt = math.degrees(math.acos(max(-1.0, min(1.0, up_cosine))))
    return {
        "frame_id": str(capture["frame_id"]), "stamp_ns": str(capture["stamp_ns"]),
        "translation_m": float(np.linalg.norm(translation)),
        "orientation_difference_deg": angle, "up_axis_difference_deg": tilt,
        # Illustrative rigid-body point 8 m forward of base_link; not an
        # actual LiDAR hit, mount correction, terrain residual or certification.
        "forward_8m_vertical_difference_m": float(translation[2] + 8 * (request[2, 0] - pose[2, 0])),
        "telemetry_wz_raw": telemetry.get("wz"),
    }


def analyze(path, *, window_s=30, max_bytes=16 * 1024 * 1024, start_stamp_ns=None, end_stamp_ns=None):
    if not 1 <= window_s <= 300:
        raise ValueError("window_s must be between 1 and 300 seconds")
    if any(value is not None and (type(value) is not int or value <= 0)
           for value in (start_stamp_ns, end_stamp_ns)):
        raise ValueError("Capture timestamp bounds must be positive integers")
    if start_stamp_ns is not None and end_stamp_ns is not None and start_stamp_ns > end_stamp_ns:
        raise ValueError("Capture timestamp bounds are reversed")
    lines, truncated = _tail_lines(path, max_bytes=max_bytes)
    telemetry, captures, rejected_telemetry, rejected_captures = _parse(lines)
    if captures:
        last = max(int(c["stamp_ns"]) for c in captures)
        captures = [c for c in captures if 0 <= last - int(c["stamp_ns"]) <= window_s * 1_000_000_000]
    captures = [c for c in captures if (start_stamp_ns is None or int(c["stamp_ns"]) >= start_stamp_ns)
                and (end_stamp_ns is None or int(c["stamp_ns"]) <= end_stamp_ns)]
    stamps = sorted(telemetry)
    pairs, ambiguous, unmatched = [], 0, 0
    for capture in captures:
        stamp = int(capture["stamp_ns"])
        i = bisect_left(stamps, stamp)
        nearby = [t for t in stamps[max(0, i - 1) : min(len(stamps), i + 2)]
                  if abs(t - stamp) <= CAPTURE_CLOCK_TOLERANCE_NS]
        if not nearby:
            unmatched += 1
            continue
        if len(nearby) != 1 or len(telemetry[nearby[0]]) != 1:
            ambiguous += 1
            continue
        try:
            frames = TurkishRoverTelemetryStream().feed(telemetry[nearby[0]][0].encode("ascii"))
            if len(frames) != 1:
                raise ValueError("Expected one telemetry object")
            pairs.append(_metrics(capture, frames[0]))
        except (ValueError, TypeError, KeyError, UnicodeError):
            rejected_telemetry += 1
            unmatched += 1

    def summary(key):
        values = sorted(abs(p[key]) for p in pairs)
        if not values:
            return None
        return {"median_abs": statistics.median(values),
                "p95_abs": values[max(0, math.ceil(0.95 * len(values)) - 1)], "max_abs": values[-1]}

    return {"status": "matched" if pairs else "no_matched_frames", "window_s": window_s,
            "log_tail_truncated": truncated, "capture_records": len(captures),
            "first_capture_stamp_ns": str(min(int(c["stamp_ns"]) for c in captures)) if captures else None,
            "last_capture_stamp_ns": str(max(int(c["stamp_ns"]) for c in captures)) if captures else None,
            "telemetry_records": sum(map(len, telemetry.values())), "matched_frames": len(pairs),
            "unmatched_captures": unmatched, "ambiguous_captures": ambiguous,
            "rejected_telemetry_lines": rejected_telemetry, "rejected_capture_lines": rejected_captures,
            "translation_m": summary("translation_m"),
            "orientation_difference_deg": summary("orientation_difference_deg"),
            "up_axis_difference_deg": summary("up_axis_difference_deg"),
            "forward_8m_vertical_difference_m": summary("forward_8m_vertical_difference_m"),
            "largest_tilt_examples": sorted(pairs, key=lambda p: p["up_axis_difference_deg"], reverse=True)[:5],
            "limits": "Request-time body pose versus telemetry with the same simulation stamp; "
                      "the 8 m point is illustrative. GPU render-time pose and terrain error are not measured."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path, help="Unreal log containing tr-TR rover telemetry and opt-in pose lines")
    parser.add_argument("--window-seconds", type=float, default=30)
    args = parser.parse_args()
    try:
        result = analyze(args.log, window_s=args.window_seconds)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Analiz yapilamadi: {error}\n")
    print("MARS_LIDAR_POSE_ANALYSIS:", json.dumps(result, ensure_ascii=False, allow_nan=False))
    if result["status"] != "matched":
        parser.exit(2, "Eslesen kare bulunamadi; LiDAR pose ve rover telemetri loglarini kontrol edin.\n")


if __name__ == "__main__":
    main()
