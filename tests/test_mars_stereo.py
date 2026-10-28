import importlib

import numpy as np
import pytest

from mars_rover.sensors import CameraFrame


def test_sgbm_recovers_depth_of_a_known_shifted_textured_plane():
    module = importlib.import_module("mars_rover.stereo")
    rng = np.random.default_rng(42)
    left = rng.integers(0, 255, (64, 192, 4), dtype="uint8")
    left[:, :, 3] = 255
    right = np.zeros_like(left)
    right[:, :-8] = left[:, 8:]
    a, b = CameraFrame(0, 7, 123, 1, left), CameraFrame(1, 7, 123, 1, right)
    result = module.stereo_pair_depth(
        a,
        b,
        {
            "left_id": 0,
            "right_id": 1,
            "hfov_deg": 90,
            "baseline_m": 0.2,
            "rectified_parallel": True,
            "width": 192,
            "height": 64,
        },
    )
    depth = result.depth_m()[8:-8, 80:-24]
    assert np.isfinite(depth).mean() > 0.8
    assert np.nanmedian(depth) == pytest.approx(2.4, abs=0.03)


def test_stereo_does_not_pair_different_captures_or_assume_rectification():
    module = importlib.import_module("mars_rover.stereo")
    image = np.zeros((32, 192, 4), dtype="uint8")
    a, b = CameraFrame(0, 1, 10, 1, image), CameraFrame(1, 2, 20, 1, image)
    with pytest.raises(ValueError):
        module.stereo_pair_depth(a, b, {"left_id": 0, "right_id": 1, "hfov_deg": 90, "baseline_m": 0.2})
