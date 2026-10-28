"""Check the shipped real-data crop against independently read source samples.

These expected elevations were read from the USGS source raster on 2026-10-28,
not derived from the converter. CI does not contact the data provider.
"""
import importlib.util
import json
import hashlib
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parents[1]


def test_frozen_dense_review_matches_the_exact_shipped_manifest():
    path = ROOT / "Content/Mars/Jezero/manifest.json"
    report = json.loads((ROOT / "docs/data/jezero-fidelity.json").read_text())
    manifest = json.loads(path.read_text())
    assert report["bundle_manifest_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    comparison = report["source_comparison"]
    assert comparison["sample_count"] == 64009
    assert comparison["max_abs_error_m"] <= comparison["tolerance_m"]
    assert comparison["source_file_sha256"] == manifest["source"]["attribution"]["source_file_sha256"]
    assert set(report["source_documents_verified"]) == {"source_dem.xml", "source_ortho.xml"}
    assert report["engine_collision_verified"] is False


def test_starter_is_a_252_m_measured_crop_with_recorded_provenance():
    path = ROOT / "Content/Mars/Jezero/manifest.json"
    m = json.loads(path.read_text())
    assert m["grid"]["extent_m"] == [252, 252]
    assert m["grid"]["resolution_m"] == 1
    assert m["source"]["window_col_row_width_height"] == [3278, 6970, 505, 505]
    assert m["source"]["reprojection"]["warp_transform_tolerance_px"] == 0.0
    assert m["source"]["reprojection"]["source_x_ground_scale_at_center"] == pytest.approx(0.9487174175)
    assert "asc-pds-services.s3.us-west-2.amazonaws.com" in m["source"]["uri"]
    spec = importlib.util.spec_from_file_location("mars_setup", ROOT / "Content/Python/mars_setup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.load_bundle(path)  # all packaged hashes and layout must agree
    elevation = np.loadtxt(path.parent / "elevation.csv") + m["vertical_datum_offset_m"]
    for row, col, source_height in [
        (0, 0, -2574.40281897754), (0, 252, -2580.473424176266),
        (252, 0, -2572.8225561898707), (252, 252, -2574.6467760063706),
        (126, 126, -2575.2473144525484),
    ]:
        assert elevation[row, col] == pytest.approx(source_height, abs=2e-6, rel=0)


def test_registered_ortho_has_independently_sampled_source_orientation():
    from PIL import Image
    image = Image.open(ROOT / "Content/Mars/Jezero/ortho_reference.png")
    assert image.size == (1024, 1024)
    for row, col, expected in [(0, 0, 46), (512, 512, 59), (1023, 1023, 90)]:
        actual = image.getpixel((col, row))
        assert actual[0] == actual[1] == actual[2]
        assert abs(actual[0] - expected) <= 1
