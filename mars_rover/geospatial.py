"""Mars CRS validation and a local, metre-correct driving grid.

Equatorial equirectangular source grid spacing is not ground spacing at Jezero.
Reproject to a small Mars azimuthal-equidistant grid before Unreal import.
"""
import math

import numpy as np
from pyproj import CRS, Transformer
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject

from .terrain import Dem


def mars_crs(value):
    crs = CRS.from_user_input(value)
    ellipsoid = crs.ellipsoid
    # Accommodate common Mars reference spheres/ellipsoids, never Earth/Moon.
    if not (3_300_000 < ellipsoid.semi_minor_metre <= ellipsoid.semi_major_metre < 3_500_000):
        raise ValueError("A Mars reference body is required; Earth/Moon rasters cannot be labelled Mars")
    return crs


def grid_transform(dem):
    """North-up raster pixel-corner transform; Dem.origin is SW vertex centre."""
    r = dem.resolution_m
    return from_origin(dem.projected_origin_m[0] - r / 2,
                       dem.projected_origin_m[1] + (dem.elevation_m.shape[0] - 0.5) * r, r, r)


def local_metric_dem(dem, *, size=253, resolution_m=1.0):
    if type(size) is not int or not 3 <= size <= 4033 or size % 2 != 1:
        raise ValueError("Local grid size must be an odd integer in 3..4033")
    if not math.isfinite(resolution_m) or resolution_m <= 0 or (size - 1) * resolution_m > 4096:
        raise ValueError("Use positive resolution and a local extent at most 4096 m")
    source_crs = mars_crs(dem.grid_crs_wkt)
    h, w = dem.elevation_m.shape
    cx = dem.projected_origin_m[0] + (w - 1) * dem.resolution_m / 2
    cy = dem.projected_origin_m[1] + (h - 1) * dem.resolution_m / 2
    lon, lat = Transformer.from_crs(source_crs, source_crs.geodetic_crs, always_xy=True).transform(cx, cy)
    a, b = source_crs.ellipsoid.semi_major_metre, source_crs.ellipsoid.semi_minor_metre
    target = CRS.from_proj4(f"+proj=aeqd +lat_0={lat:.12f} +lon_0={lon:.12f} +a={a} +b={b} +units=m +no_defs")
    half = (size - 1) * resolution_m / 2
    target_transform = from_origin(-half - resolution_m / 2, half + resolution_m / 2,
                                   resolution_m, resolution_m)
    data = np.full((size, size), np.nan, dtype="float64")
    reproject(np.flipud(dem.elevation_m), data, src_transform=grid_transform(dem),
              src_crs=source_crs.to_wkt(), dst_transform=target_transform, dst_crs=target.to_wkt(),
              src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.bilinear, tolerance=0,
              XSCALE=1, YSCALE=1)
    if not np.isfinite(data).all():
        raise ValueError("Requested local grid exceeds measured DEM coverage; use a larger source window")
    # For eqc, record the source's east-west ground/grid scale at the centre.
    source_scale = None
    operation = source_crs.coordinate_operation
    if operation and operation.method_name.startswith("Equidistant Cylindrical"):
        lat_ts = next((p.value for p in operation.params if p.name == "Latitude of 1st standard parallel"), 0)
        source_scale = math.cos(math.radians(lat)) / math.cos(math.radians(lat_ts))
    source = {**dem.source, "reprojection": {
        "method": "bilinear; Mars azimuthal equidistant centred on source window",
        "warp_transform_tolerance_px": 0.0,
        "height_interpolation": "bilinear point sampling; XSCALE=YSCALE=1, no footprint averaging",
        "center_longitude_deg": lon, "center_latitude_deg": lat,
        "source_x_ground_scale_at_center": source_scale,
        "reference_semi_major_m": a, "reference_semi_minor_m": b,
        "geometry_model": "planar local heightfield; no planetary curvature displacement",
        "max_reference_sphere_sag_m": 2 * half * half / (2 * b),
    }}
    return Dem(np.flipud(data).copy(), resolution_m, (-half, -half), source, target.to_wkt())
