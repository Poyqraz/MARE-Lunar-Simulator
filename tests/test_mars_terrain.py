"""Behavioral contracts: geospatial orientation, vertical scale and invalid cells."""
import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from mars_rover.terrain import prepare_bundle, read_dem

MARS_CRS = "+proj=eqc +lat_ts=0 +R=3396190 +units=m +no_defs"


def make_dem(path, values, *, resolution=2.0, nodata=None, scale=1.0, offset=0.0,
             crs=MARS_CRS, transform=None):
    with rasterio.open(path, "w", driver="GTiff", width=values.shape[1],
                       height=values.shape[0], count=1, dtype=values.dtype,
                       crs=crs, transform=transform or from_origin(100, 200, resolution, resolution),
                       nodata=nodata) as ds:
        ds.write(values, 1)
        ds.scales = (scale,)
        ds.offsets = (offset,)
        ds.set_band_unit(1, "m")
    return path


def test_crop_preserves_zero_negative_heights_and_applies_scale_offset(tmp_path):
    data = np.arange(-12, 13, dtype="int16").reshape(5, 5)
    source = make_dem(tmp_path / "dem.tif", data, scale=0.5, offset=-100)
    dem = read_dem(str(source), window=(1, 1, 3, 3), vertical_unit="m")
    np.testing.assert_array_equal(dem.elevation_m, data[1:4, 1:4][::-1] * 0.5 - 100)
    assert dem.resolution_m == 2.0
    assert dem.projected_origin_m == (103.0, 193.0)


def test_bundle_has_same_coordinates_for_unreal_gnc_and_source(tmp_path):
    # Asymmetric, real elevations may be below the Mars aeroid or exactly zero.
    values = np.array([[-9, -7, -5], [-4, 0, 2], [3, 6, 10]], dtype="float32")
    source = make_dem(tmp_path / "dem.tif", values)
    manifest_path = prepare_bundle(read_dem(str(source), vertical_unit="m"), tmp_path / "out")
    m = json.loads(manifest_path.read_text())
    elevation = np.loadtxt(tmp_path / "out" / "elevation.csv")
    assert b"\r" not in (tmp_path / "out" / "elevation.csv").read_bytes()
    assert b"\r" not in (tmp_path / "out" / "soil.csv").read_bytes()
    np.testing.assert_allclose(elevation, values[::-1] + 9)
    layout = m["landscape"]
    h = np.fromfile(tmp_path / "out" / "heightmap.r16", dtype="<u2").reshape(layout["height"], layout["width"])
    # Landscape vertex (W-1-col,row) -> UE (-col*r,row*r) -> GNC (col*r,row*r).
    for row, col in [(0, 0), (0, 2), (2, 0), (2, 2), (1, 1)]:
        ix = layout["width"] - 1 - col
        x_ue = layout["location_cm"][0] + ix * layout["scale"][0]
        y_ue = layout["location_cm"][1] + row * layout["scale"][1]
        assert (-x_ue / 100, y_ue / 100) == (col * 2, row * 2)
        z = layout["location_cm"][2] / 100 + (int(h[row, ix]) - 32768) * layout["scale"][2] / 12800
        assert z == pytest.approx(elevation[row, col], abs=m["vertical_quantization_m"])
    assert m["vertical_datum_offset_m"] == -9
    assert m["grid"]["extent_m"] == [4, 4]
    assert m["grid"]["row_direction"] == "north"
    soil = np.loadtxt(tmp_path / "out" / "soil.csv")
    assert soil[1, 1] == 1
    assert np.all(soil[[0, -1]] == 0)
    assert np.all(soil[:, [0, -1]] == 0)
    assert m["surface_model"] == "rigid_heightfield; soil.csv is a no-go mask, not measured soil"


def test_invalid_cells_are_rejected_instead_of_becoming_drivable_pits(tmp_path):
    data = np.ones((5, 5), dtype="float32")
    data[2, 2] = -9999
    source = make_dem(tmp_path / "dem.tif", data, nodata=-9999)
    with pytest.raises(ValueError, match="NoData"):
        read_dem(str(source), vertical_unit="m")


@pytest.mark.parametrize("window", [(-1, 0, 3, 3), (0, 0, 6, 3), (0, 0, 1, 3)])
def test_bad_crop_is_rejected(tmp_path, window):
    source = make_dem(tmp_path / "dem.tif", np.ones((5, 5), dtype="float32"))
    with pytest.raises(ValueError):
        read_dem(str(source), window=window, vertical_unit="m")


def test_geographic_degrees_cannot_be_mistaken_for_metres(tmp_path):
    source = make_dem(tmp_path / "dem.tif", np.ones((5, 5), dtype="float32"), crs="EPSG:4326")
    with pytest.raises(ValueError, match="projected.*met"):
        read_dem(str(source), vertical_unit="m")


def test_rectangular_pixels_require_reprojection(tmp_path):
    source = make_dem(tmp_path / "dem.tif", np.ones((5, 5), dtype="float32"),
                      transform=from_origin(100, 200, 1, 2))
    with pytest.raises(ValueError, match="square"):
        read_dem(str(source), vertical_unit="m")


def test_flat_dem_still_has_positive_z_scale_and_no_terracing(tmp_path):
    source = make_dem(tmp_path / "dem.tif", np.full((4, 4), -4200, dtype="float32"))
    m = json.loads(prepare_bundle(read_dem(str(source), vertical_unit="m"), tmp_path / "out").read_text())
    assert m["landscape"]["scale"][2] > 0
    assert np.all(np.loadtxt(tmp_path / "out" / "elevation.csv") == 0)


def test_existing_output_is_not_overwritten(tmp_path):
    source = make_dem(tmp_path / "dem.tif", np.ones((4, 4), dtype="float32"))
    dem = read_dem(str(source), vertical_unit="m")
    prepare_bundle(dem, tmp_path / "out")
    with pytest.raises(FileExistsError):
        prepare_bundle(dem, tmp_path / "out")


def test_earth_dem_cannot_be_silently_labelled_mars(tmp_path):
    source = make_dem(tmp_path / "earth.tif", np.ones((5, 5), dtype="float32"), crs="EPSG:32631")
    with pytest.raises(ValueError, match="Mars"):
        read_dem(str(source), vertical_unit="m")


def test_nonfinite_raster_geotransform_is_rejected_before_read(tmp_path):
    from affine import Affine
    source = make_dem(tmp_path / "bad.tif", np.ones((5, 5), dtype="float32"),
                      transform=Affine(float("nan"), 0, 100, 0, -1, 200))
    with pytest.raises(ValueError, match="finite"):
        read_dem(str(source), vertical_unit="m")


def test_custom_source_requires_explicit_region_instead_of_defaulting_to_jezero(tmp_path):
    from mars_rover.prepare import main
    with pytest.raises(SystemExit) as error:
        main(["--source", "different_mars_region.tif", "--output", str(tmp_path / "out")])
    assert error.value.code == 2
