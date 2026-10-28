"""Convert a projected DEM to one coordinate-consistent Unreal/GNC bundle.

Source rasters are north-up; output rows run south-to-north, so local ROS
x/east, y/north, z/up form a right-handed frame. Unreal uses (-x, y, z) cm,
matching MARE's rover telemetry conversion. No procedural relief is added.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile

import numpy as np


@dataclass
class Dem:
    elevation_m: np.ndarray
    resolution_m: float
    projected_origin_m: tuple
    source: dict
    grid_crs_wkt: str | None = None


def read_dem(source: str, *, window=None, vertical_unit: str) -> Dem:
    """Read only a selected pixel window. Refuse ambiguous or missing geometry.

    A caller must explicitly assert metres vertically. GDAL band scale/offset
    are applied; zero and negative heights remain valid. NoData is refused,
    never interpolated into an apparently safe driving surface.
    """
    import rasterio
    from rasterio.windows import Window

    if vertical_unit != "m":
        raise ValueError("DEM vertical units must be metres ('m')")
    env = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "GDAL_HTTP_TIMEOUT": "30"}
    # Respect a host's trusted CA configuration without disabling TLS checks.
    if os.environ.get("SSL_CERT_FILE"):
        env["CURL_CA_BUNDLE"] = os.environ["SSL_CERT_FILE"]
    with rasterio.Env(**env), rasterio.open(source) as ds:
        t = ds.transform
        if not all(math.isfinite(v) for v in list(t)[:6]):
            raise ValueError("DEM geotransform must be finite")
        if not ds.crs or not ds.crs.is_projected or ds.crs.linear_units not in ("metre", "meter"):
            raise ValueError("Use a projected CRS in metres; reproject geographic/degrees data first")
        from .geospatial import mars_crs
        mars_crs(ds.crs.to_wkt())
        if t.a <= 0 or t.e >= 0 or abs(t.b) > 1e-10 or abs(t.d) > 1e-10:
            raise ValueError("Use a north-up, unrotated DEM; reproject first")
        if not math.isclose(t.a, -t.e, rel_tol=1e-7):
            raise ValueError("DEM pixels must be square; resample first")
        if ds.count != 1:
            raise ValueError("Select a single-band elevation DEM, not a colour/orthoimage")
        if ds.units[0] and ds.units[0].lower() not in ("m", "metre", "meter", "metres", "meters"):
            raise ValueError("DEM band declares non-metre vertical units")
        col, row, width, height = window if window is not None else (0, 0, ds.width, ds.height)
        if any(isinstance(v, bool) or not isinstance(v, int) for v in (col, row, width, height)):
            raise ValueError("Window must be integer COL ROW WIDTH HEIGHT")
        if col < 0 or row < 0 or width < 3 or height < 3 or col + width > ds.width or row + height > ds.height:
            raise ValueError("Window must be inside the DEM and at least 3 by 3 pixels")
        if max(width, height) > 4097:
            raise ValueError("Crop to at most 4097 vertices per side for automatic Unreal import")
        values = ds.read(1, window=Window(col, row, width, height), masked=True).astype("float64")
        if np.ma.getmaskarray(values).any():
            raise ValueError("Selected crop contains NoData; choose a fully covered region")
        scale, offset = ds.scales[0], ds.offsets[0]
        elevation = np.asarray(values) * scale + offset
        if not np.isfinite(elevation).all():
            raise ValueError("Selected crop contains NoData or non-finite heights")
        # Lower-left pixel CENTRE is local (0,0); each sample becomes a vertex.
        origin = (t.a * (col + 0.5) + t.c, t.e * (row + height - 0.5) + t.f)
        return Dem(np.flipud(elevation).copy(), float(t.a), origin, {
            "uri": str(source), "window_col_row_width_height": [col, row, width, height],
            "crs_wkt": ds.crs.to_wkt(), "raster_transform": list(t)[:6],
            "band_scale": scale, "band_offset": offset, "vertical_unit": "m",
        }, ds.crs.to_wkt())


def landscape_layout(width: int, height: int) -> dict:
    """Choose a standard UE layout without resampling or stretching the DEM."""
    options = []
    for section in (63, 127, 255):
        for sections in (1, 2):
            q = section * sections
            cx, cy = math.ceil((width - 1) / q), math.ceil((height - 1) / q)
            w, h = cx * q + 1, cy * q + 1
            if max(w, h) <= 4097 and cx * cy <= 1024:
                options.append((w * h, cx * cy, section, sections, cx, cy, w, h))
    if not options:
        raise ValueError("Crop is too large for this single-Landscape importer")
    _, _, section, sections, cx, cy, w, h = min(options)
    return dict(section_size=section, sections_per_component=sections,
                component_count_x=cx, component_count_y=cy, width=w, height=h)


def prepare_bundle(dem: Dem, output, *, region="jezero", attribution=None, imagery=None) -> Path:
    """Write a reproducible bundle atomically; never replace an existing output."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}; choose a new folder")
    data = np.asarray(dem.elevation_m, dtype="float64")
    if data.ndim != 2 or min(data.shape) < 3 or not np.isfinite(data).all():
        raise ValueError("DEM must be a finite 2D grid, at least 3 by 3")
    if not math.isfinite(dem.resolution_m) or dem.resolution_m <= 0:
        raise ValueError("DEM resolution must be positive metres per pixel")
    height, width = data.shape
    layout = landscape_layout(width, height)
    datum = float(data.min())
    local = data - datum
    span = max(float(np.ptp(local)), 0.001)
    z_scale = span * 100 * 128 / 65535
    encoded = np.rint(local / span * 65535).astype("<u2")
    encoded = np.pad(encoded, ((0, layout["height"] - height),
                              (0, layout["width"] - width)), mode="edge")
    # Mirroring and the X offset implement UE.x=-ROS.x, not an arbitrary flip.
    r = dem.resolution_m
    layout["scale"] = [r * 100, r * 100, z_scale]
    layout["location_cm"] = [-(layout["width"] - 1) * r * 100, 0, 32768 * z_scale / 128]
    soil = np.ones(data.shape, dtype="uint8")
    soil[[0, -1], :] = 0
    soil[:, [0, -1]] = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".mars-", dir=output.parent))
    try:
        np.ascontiguousarray(np.fliplr(encoded), dtype="<u2").tofile(stage / "heightmap.r16")
        with (stage / "elevation.csv").open("w", encoding="utf-8", newline="\n") as handle:
            np.savetxt(handle, local, fmt="%.9f", delimiter=" ")
        with (stage / "soil.csv").open("w", encoding="utf-8", newline="\n") as handle:
            np.savetxt(handle, soil, fmt="%d", delimiter=" ")
        manifest = {
            "schema_version": 1, "planet": "mars", "region": region,
            "gravity_m_s2": 3.71, "source": {**dem.source, "attribution": attribution or {}},
            "grid": {"width": width, "height": height, "resolution_m": r,
                     "extent_m": [(width - 1) * r, (height - 1) * r],
                     "row_direction": "north", "column_direction": "east",
                     "projected_origin_m": list(dem.projected_origin_m),
                     "crs_wkt": dem.grid_crs_wkt},
            "vertical_datum_offset_m": datum, "vertical_quantization_m": span / 65535,
            "landscape": layout,
            "surface_model": "rigid_heightfield; soil.csv is a no-go mask, not measured soil",
            "files": {},
        }
        for name in ("heightmap.r16", "elevation.csv", "soil.csv"):
            manifest["files"][name] = {"sha256": hashlib.sha256((stage / name).read_bytes()).hexdigest()}
        if imagery is not None:
            from PIL import Image
            if imagery.rgb.dtype != np.uint8 or imagery.rgb.ndim != 3 or imagery.rgb.shape[2] != 3:
                raise ValueError("Ortho reference must be uint8 RGB display data")
            filename = "ortho_reference.png"
            Image.fromarray(imagery.rgb).save(stage / filename)
            manifest["files"][filename] = {"sha256": hashlib.sha256((stage / filename).read_bytes()).hexdigest()}
            manifest["imagery"] = {
                "filename": filename, "width": imagery.rgb.shape[1], "height": imagery.rgb.shape[0],
                "uv_mapping": "u=local_x/extent_x; v=1-local_y/extent_y",
                "source": imagery.source,
            }
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n",
                                              encoding="utf-8", newline="\n")
        stage.rename(output)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return output / "manifest.json"
