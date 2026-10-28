"""Optional OpenCV SGBM on a measured, parallel rectified Unreal stereo rig.

Output is LEFT optical-frame planar metres. Central-camera ground truth is a
different viewpoint and must not be compared pixel-for-pixel with this output.
"""

from dataclasses import dataclass
import math

import numpy as np


@dataclass
class StereoDepth:
    camera_id: int
    frame_id: int
    stamp_ns: int
    metres: np.ndarray

    def depth_m(self):
        return self.metres


def stereo_pair_depth(left, right, rig):
    if (
        left.format != 1
        or right.format != 1
        or left.frame_id != right.frame_id
        or left.stamp_ns is None
        or left.stamp_ns != right.stamp_ns
        or left.camera_id != rig.get("left_id")
        or right.camera_id != rig.get("right_id")
        or rig.get("rectified_parallel") is not True
        or left.pixels.shape != right.pixels.shape
    ):
        raise ValueError("Stereo requires the same capture and a measured parallel/rectified pair")
    h, w = left.pixels.shape[:2]
    if (
        rig.get("width") != w
        or rig.get("height") != h
        or w * h > 1_048_576
        or w < 96
        or h < 16
        or not 0 < rig.get("hfov_deg", 0) < 180
        or not 0 < rig.get("baseline_m", 0) < 10
    ):
        raise ValueError("Stereo resolution/intrinsics/baseline disagree with calibration")
    try:
        import cv2
    except ImportError as error:
        raise RuntimeError("Install requirements-mars-stereo.txt for stereo mode") from error
    # With 64 disparities, very near pixels outside the pair's overlap remain
    # invalid. No padding or hole filling turns them into fictitious geometry.
    matcher = cv2.StereoSGBM_create(
        minDisparity=0,
        numDisparities=64,
        blockSize=5,
        P1=8 * 25,
        P2=32 * 25,
        disp12MaxDiff=1,
        uniquenessRatio=10,
        speckleWindowSize=50,
        speckleRange=2,
        mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY,
    )
    a, b = cv2.cvtColor(left.pixels, cv2.COLOR_BGRA2GRAY), cv2.cvtColor(right.pixels, cv2.COLOR_BGRA2GRAY)
    disparity = matcher.compute(a, b).astype(float) / 16  # OpenCV fixed-point disparity
    fx = w / (2 * math.tan(math.radians(rig["hfov_deg"]) / 2))
    with np.errstate(divide="ignore", invalid="ignore"):
        depth = fx * rig["baseline_m"] / disparity
    depth[(disparity <= 0) | (~np.isfinite(depth)) | (depth >= 100) | (depth <= 0)] = np.nan
    return StereoDepth(left.camera_id, left.frame_id, left.stamp_ns, depth)
