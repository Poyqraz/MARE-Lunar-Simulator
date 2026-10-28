"""Numerical fidelity is distinct from accuracy of the orbital measurements."""
import importlib
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from mars_rover.terrain import Dem, prepare_bundle, read_dem


def fidelity():
    return importlib.import_module("mars_rover.fidelity")


def test_scale_dependent_slopes_do_not_hide_a_sharp_pit():
    z = np.zeros((7, 7))
    z[3, 3] = -1
    report = fidelity().terrain_metrics(z, 1)
    # Central differences cancel at the pit; actual triangle faces remain steep.
    assert report["triangle_slope_upper_bound_deg"] == pytest.approx(54.735610317)
    assert report["central_difference_slopes"]["2"]["max_deg"] < 30
    assert report["height_range_m"] == 1
    assert report["wheel_scale_obstacles_validated"] is False


def test_slope_baseline_and_units_are_explicit():
    y, x = np.mgrid[:25, :25]
    report = fidelity().terrain_metrics(0.2 * x + 0.1 * y, 2)
    angle = np.degrees(np.arctan(np.hypot(0.1, 0.05)))
    assert report["triangle_slope_upper_bound_deg"] == pytest.approx(angle)
    for values in report["central_difference_slopes"].values():
        assert values["max_deg"] == pytest.approx(angle)


def test_full_grid_source_audit_catches_a_rotated_or_shifted_bundle(tmp_path):
    source = tmp_path / "source.tif"
    y, x = np.mgrid[:9, :9]
    values = (2 * x + 3 * y - 50).astype("float32")
    crs = "+proj=eqc +R=3396190 +units=m +no_defs"
    with rasterio.open(source, "w", driver="GTiff", width=9, height=9, count=1,
                       dtype="float32", crs=crs, transform=from_origin(0, 9, 1, 1)) as ds:
        ds.write(values, 1)
    dem = read_dem(str(source), window=(1, 1, 7, 7), vertical_unit="m")
    path = prepare_bundle(dem, tmp_path / "bundle")
    report = fidelity().audit_bundle(path, source_dem=source)
    assert report["source_comparison"]["sample_count"] == 49
    assert report["source_comparison"]["max_abs_error_m"] < 1e-8
    manifest = json.loads(path.read_text())
    manifest["grid"]["projected_origin_m"][0] += 1
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="source|Source"):
        fidelity().audit_bundle(path, source_dem=source)


def test_audit_of_shipped_bundle_never_claims_runtime_or_microgeometry():
    path = Path(__file__).parents[1] / "Content/Mars/Jezero/manifest.json"
    report = fidelity().audit_bundle(path)
    assert report["heightfield_encoding"]["max_abs_error_m"] < 0.0000611
    assert report["terrain"]["triangle_slope_upper_bound_deg"] > 21
    assert report["source_comparison"] is None
    assert report["engine_collision_verified"] is False
    assert report["photometry_validated"] is False


def test_original_metadata_bytes_are_hashed_and_checked(tmp_path, monkeypatch):
    dem = Dem(np.zeros((3, 3)), 1, (0, 0), {"uri": "test"})
    xml = b'<?xml version="1.0"?><metadata><title>USGS source</title></metadata>\r\n'
    path = prepare_bundle(dem, tmp_path / "bundle", source_documents={
        "source_dem.xml": {"uri": "https://example.org/source.xml", "content": xml}})
    assert (path.parent / "source_dem.xml").read_bytes() == xml
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "Content/Python"))
    setup = importlib.import_module("mars_setup")
    setup.load_bundle(path)
    (path.parent / "source_dem.xml").write_bytes(xml + b'changed')
    with pytest.raises(ValueError, match="hash"):
        setup.load_bundle(path)
