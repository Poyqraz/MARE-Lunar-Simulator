"""Bounded LiDAR/depth comparison for observation, never motion control.

Both clouds must already be transformed with their respective capture-time
poses. A shared small XY bin is not the same ray, proof of a free cell, or an
independently measured physical surface.
"""

import math

import numpy as np


MAX_SAMPLE_POINTS = 8192
BIN_METRES = 0.25


def bounded_sample(points):
    """Copy at most MAX_SAMPLE_POINTS in deterministic input order."""
    points = np.asarray(points)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("Expected Nx3 world points")
    count = len(points)
    if count > MAX_SAMPLE_POINTS:
        indices = np.linspace(0, count - 1, MAX_SAMPLE_POINTS, dtype=np.int64)
        return points[indices].copy(), count
    return points.copy(), count


def _bins(points, heights, resolution, bin_width, threshold):
    h, w = heights.shape
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("Expected Nx3 world points")
    if len(points) > MAX_SAMPLE_POINTS:
        raise ValueError("Shadow comparison input exceeds the sample budget")
    # Bound index calculations and temporary allocations for unusual grids.
    extent_x, extent_y = (w - 1) * resolution, (h - 1) * resolution
    if max(extent_x, extent_y) > 1_000_000:
        raise ValueError("Shadow comparison terrain extent exceeds the budget")
    valid = (np.isfinite(points).all(axis=1) & (points[:, 0] >= 0) & (points[:, 0] <= extent_x)
             & (points[:, 1] >= 0) & (points[:, 1] <= extent_y))
    points = points[valid]
    col, row = points[:, 0] / resolution, points[:, 1] / resolution
    i, j = np.minimum(row.astype(int), h - 2), np.minimum(col.astype(int), w - 2)
    dy, dx = row - i, col - j
    surface = ((1 - dy) * ((1 - dx) * heights[i, j] + dx * heights[i, j + 1])
               + dy * ((1 - dx) * heights[i + 1, j] + dx * heights[i + 1, j + 1]))
    residual = points[:, 2] - surface
    valid = np.isfinite(residual)
    points, residual = points[valid], residual[valid]
    columns = math.floor(extent_x / bin_width) + 1
    xbin = np.floor(points[:, 0] / bin_width).astype(np.int64)
    ybin = np.floor(points[:, 1] / bin_width).astype(np.int64)
    keys, inverse = np.unique(ybin * columns + xbin, return_inverse=True)
    flags = np.zeros(len(keys), dtype=np.uint8)
    point_flags = np.zeros(len(points), dtype=np.uint8)
    point_flags[np.abs(residual) <= threshold / 3] |= 1
    point_flags[residual > threshold] |= 2
    point_flags[residual < -threshold] |= 4
    point_flags[(point_flags & 7) == 0] |= 8  # Intermediate residual, not ground-like.
    np.bitwise_or.at(flags, inverse, point_flags)
    return keys, flags, len(points)


def compare_sampled_clouds(lidar, depth, heights, resolution, threshold):
    """Compare height residual categories in shared 25 cm map-space bins.

    Ground-like and hazard-like returns within a bin can be different points,
    objects, beams or occluded surfaces. Sampling may miss an obstacle.
    The result must never remove occupied cells or authorize movement.
    """
    heights = np.asarray(heights, dtype=np.float64)
    if (heights.ndim != 2 or min(heights.shape) < 3 or not math.isfinite(resolution) or resolution <= 0
            or not math.isfinite(threshold) or threshold <= 0):
        raise ValueError("Invalid terrain or residual threshold")
    lk, lf, ln = _bins(lidar, heights, resolution, BIN_METRES, threshold)
    dk, df, dn = _bins(depth, heights, resolution, BIN_METRES, threshold)
    _, li, di = np.intersect1d(lk, dk, assume_unique=True, return_indices=True)
    left, right = lf[li], df[di]
    lhazard, dhazard = (left & 6) != 0, (right & 6) != 0
    # Mixed ground-like/intermediate/hazard returns are ambiguous.
    lground_only = ((left & 1) != 0) & ((left & 14) == 0)
    dground_only = ((right & 1) != 0) & ((right & 14) == 0)
    return {
        "bin_size_m": BIN_METRES, "ground_like_band_m": threshold / 3,
        "hazard_residual_threshold_m": threshold,
        "lidar_valid_sample_points": ln, "depth_valid_sample_points": dn,
        "shared_bins": int(len(li)),
        "lidar_hazard_depth_ground_like_bins": int(np.count_nonzero(lhazard & dground_only)),
        "lidar_positive_depth_ground_like_bins": int(np.count_nonzero(((left & 2) != 0) & dground_only)),
        "lidar_negative_depth_ground_like_bins": int(np.count_nonzero(((left & 4) != 0) & dground_only)),
        "depth_hazard_lidar_ground_like_bins": int(np.count_nonzero(dhazard & lground_only)),
        "both_sensors_hazard_like_bins": int(np.count_nonzero(lhazard & dhazard)),
        "limits": "Display-only sampled bin comparison; shared bins are not matching rays or proof of clearance. "
                  "Ground truth is simulated depth; render-time pose and full coverage are unverified.",
    }
