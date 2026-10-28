"""Register a measured single-band orthoimage to the exact local DEM extent.

This is display-stretched reference imagery, not recovered albedo or true colour.
Use an unlit reference material so baked orbital shadows are not relit twice.
"""
from dataclasses import dataclass
import math
import os

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject, transform_bounds
from rasterio.windows import Window, from_bounds

from .geospatial import mars_crs


@dataclass
class OrthoImage:
    rgb: np.ndarray
    source: dict


def read_ortho(source, dem, *, size=1024):
    if type(size) is not int or not 4 <= size <= 4096:
        raise ValueError("Texture size must be an integer in 4..4096")
    target_crs = mars_crs(dem.grid_crs_wkt)
    r = dem.resolution_m
    extent_x, extent_y = (dem.elevation_m.shape[1] - 1) * r, (dem.elevation_m.shape[0] - 1) * r
    x0, y0 = dem.projected_origin_m
    target_transform = from_origin(x0, y0 + extent_y, extent_x / size, extent_y / size)
    env = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "GDAL_HTTP_TIMEOUT": "30"}
    if os.environ.get("SSL_CERT_FILE"):
        env["CURL_CA_BUNDLE"] = os.environ["SSL_CERT_FILE"]
    with rasterio.Env(**env), rasterio.open(source) as ds:
        mars_crs(ds.crs.to_wkt())
        if ds.count != 1:
            raise ValueError("Only a documented single-band grayscale orthoimage is supported")
        if (not all(math.isfinite(v) for v in list(ds.transform)[:6]) or
                ds.transform.a <= 0 or ds.transform.e >= 0 or ds.transform.b or ds.transform.d):
            raise ValueError("Use a finite, north-up orthoimage transform")
        bounds = transform_bounds(target_crs.to_wkt(), ds.crs,
                                  x0, y0, x0 + extent_x, y0 + extent_y, densify_pts=21)
        window = from_bounds(*bounds, transform=ds.transform)
        left, top = max(0, math.floor(window.col_off) - 2), max(0, math.floor(window.row_off) - 2)
        right = min(ds.width, math.ceil(window.col_off + window.width) + 2)
        bottom = min(ds.height, math.ceil(window.row_off + window.height) + 2)
        if right <= left or bottom <= top:
            raise ValueError("Orthoimage has no coverage of the requested terrain")
        window = Window(left, top, right - left, bottom - top)
        data = ds.read(1, window=window, masked=True).astype("float64")
        if np.ma.getmaskarray(data).any():
            raise ValueError("Orthoimage crop contains NoData; choose complete coverage")
        data = np.asarray(data) * ds.scales[0] + ds.offsets[0]
        target = np.full((size, size), np.nan, dtype="float64")
        reproject(data, target, src_transform=ds.window_transform(window), src_crs=ds.crs,
                  dst_transform=target_transform, dst_crs=target_crs.to_wkt(),
                  src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.bilinear, tolerance=0)
        if not np.isfinite(target).all():
            raise ValueError("Orthoimage has incomplete coverage or NoData on the requested grid")
        low, high = map(float, np.percentile(target, [1, 99]))
        gray = (np.rint(np.clip((target - low) / (high - low), 0, 1) * 255).astype("uint8")
                if high > low else np.full(target.shape, 128, dtype="uint8"))
        metadata = {
            "uri": str(source), "source_crs_wkt": ds.crs.to_wkt(),
            "source_window_col_row_width_height": [left, top, right - left, bottom - top],
            "source_pixel_spacing": [ds.transform.a, -ds.transform.e],
            "band_scale": ds.scales[0], "band_offset": ds.offsets[0],
            "display_stretch_percentiles": [1, 99], "display_stretch_values": [low, high],
            "interpretation": "contrast-stretched grayscale orbital reference; contains baked illumination",
            "resampling": "bilinear", "true_color": False, "albedo": False,
            "warp_transform_tolerance_px": 0.0,
        }
    return OrthoImage(np.repeat(gray[:, :, None], 3, axis=2), metadata)
