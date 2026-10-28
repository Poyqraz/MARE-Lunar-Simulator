import numpy as np
import pytest

from mars_rover.imagery import read_ortho
from mars_rover.terrain import read_dem, prepare_bundle
from test_mars_terrain import make_dem


def test_ortho_is_aligned_north_up_and_remains_identified_as_grayscale(tmp_path):
    data = np.array([[230] * 5, [180] * 5, [130] * 5, [80] * 5, [30] * 5], dtype="uint8")
    source = make_dem(tmp_path / "ortho.tif", data, resolution=1)
    dem = read_dem(str(source), vertical_unit="m")
    image = read_ortho(str(source), dem, size=16)
    assert image.rgb.shape == (16, 16, 3)
    assert image.rgb[0, 8, 0] > image.rgb[-1, 8, 0]
    np.testing.assert_array_equal(image.rgb[:, :, 0], image.rgb[:, :, 1])
    assert image.source["interpretation"] == "contrast-stretched grayscale orbital reference; contains baked illumination"
    path = prepare_bundle(dem, tmp_path / "out", imagery=image)
    import json
    m = json.loads(path.read_text())
    assert m["imagery"]["filename"] == "ortho_reference.png"
    assert (path.parent / "ortho_reference.png").is_file()
    assert m["imagery"]["uv_mapping"] == "u=local_x/extent_x; v=1-local_y/extent_y"


def test_ortho_nodata_is_not_painted_as_a_real_black_surface(tmp_path):
    data = np.ones((5, 5), dtype="uint8") * 100
    data[2, 2] = 0
    source = make_dem(tmp_path / "ortho.tif", data, nodata=0)
    terrain = make_dem(tmp_path / "dem.tif", np.ones((5, 5), dtype="float32"))
    dem = read_dem(str(terrain), vertical_unit="m")
    with pytest.raises(ValueError, match="coverage|NoData"):
        read_ortho(str(source), dem, size=16)


def test_color_image_is_not_silently_claimed_as_true_mars_color(tmp_path):
    import rasterio
    from rasterio.transform import from_origin
    from test_mars_terrain import MARS_CRS
    source = tmp_path / "rgb.tif"
    with rasterio.open(source, "w", driver="GTiff", width=5, height=5, count=3,
                       dtype="uint8", crs=MARS_CRS, transform=from_origin(100, 200, 2, 2)) as ds:
        ds.write(np.full((3, 5, 5), 100, dtype="uint8"))
    terrain = make_dem(tmp_path / "dem.tif", np.ones((5, 5), dtype="float32"))
    with pytest.raises(ValueError, match="single-band"):
        read_ortho(str(source), read_dem(str(terrain), vertical_unit="m"), size=16)
