import math

import numpy as np
import pytest
from pyproj import Geod, Transformer
from rasterio.transform import from_origin

from mars_rover.terrain import read_dem
from mars_rover.geospatial import local_metric_dem
from test_mars_terrain import make_dem


def test_equatorial_grid_metres_are_reprojected_to_local_ground_metres(tmp_path):
    # At 30N, 100 grid metres in a latitude-of-true-scale=0 projection are
    # only 86.60 m along an east/west parallel on the Mars reference sphere.
    radius = 3396190
    north = radius * math.radians(30)
    source = make_dem(tmp_path / "mars.tif", np.ones((301, 301), dtype="float32"),
                      resolution=1, transform=from_origin(-150.5, north + 150.5, 1, 1))
    dem = local_metric_dem(read_dem(str(source), vertical_unit="m"), size=101, resolution_m=1)
    assert dem.elevation_m.shape == (101, 101)
    assert dem.projected_origin_m == (-50, -50)
    transformer = Transformer.from_crs(dem.grid_crs_wkt, f"+proj=longlat +R={radius}", always_xy=True)
    lon, lat = transformer.transform([-50, 50], [0, 0])
    distance = Geod(a=radius, b=radius).inv(lon[0], lat[0], lon[1], lat[1])[2]
    assert distance == pytest.approx(100, abs=0.001)
    assert dem.source["reprojection"]["source_x_ground_scale_at_center"] == pytest.approx(math.cos(math.radians(30)), rel=1e-7)


def test_reprojection_preserves_a_planar_northward_height_gradient(tmp_path):
    data = np.repeat(np.arange(301, dtype="float64")[:, None], 301, axis=1)
    source = make_dem(tmp_path / "mars.tif", data,
                      transform=from_origin(-150.5, 150.5, 1, 1))
    local = local_metric_dem(read_dem(str(source), vertical_unit="m"), size=101, resolution_m=1)
    # Source rows increase south; local rows increase north.
    assert local.elevation_m[0, 50] == pytest.approx(200, abs=1e-5)
    assert local.elevation_m[100, 50] == pytest.approx(100, abs=1e-5)


def test_reprojection_refuses_an_area_outside_measured_coverage(tmp_path):
    source = make_dem(tmp_path / "mars.tif", np.ones((9, 9), dtype="float32"))
    with pytest.raises(ValueError, match="coverage"):
        local_metric_dem(read_dem(str(source), vertical_unit="m"), size=101, resolution_m=1)
