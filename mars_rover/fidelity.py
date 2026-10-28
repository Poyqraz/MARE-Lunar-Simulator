"""Audit a measured heightfield without confusing file fidelity with site accuracy.

    python -m mars_rover.fidelity --source-dem .cache/mars/jezero_c.tif

Optional source comparison uses inverse CRS coordinates and a direct four-post
interpolator, independently of the rasterio/GDAL warp used by preparation.
It checks every output post, not just the original five control points.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def terrain_metrics(elevation, resolution_m):
    z = np.asarray(elevation, dtype="float64")
    if (z.ndim != 2 or min(z.shape) < 3 or not np.isfinite(z).all() or
            not math.isfinite(resolution_m) or resolution_m <= 0):
        raise ValueError("Use a finite 2D height grid and positive metre spacing")
    a, b, c, d = z[:-1, :-1], z[:-1, 1:], z[1:, :-1], z[1:, 1:]
    # Both possible diagonals are covered. This is an upper bound for the
    # encoded grid, not a claim that a particular engine diagonal was observed.
    slopes = [np.degrees(np.arctan(np.hypot(dx, dy) / resolution_m)) for dx, dy in
              ((b - a, c - a), (d - c, d - b), (b - a, d - b), (d - c, c - a))]
    triangle_max = np.maximum.reduce(slopes)
    baselines = {}
    for cells in (1, 2, 5, 10):
        if min(z.shape) <= 2 * cells:
            continue
        dx = (z[cells:-cells, 2 * cells:] - z[cells:-cells, :-2 * cells]) / (2 * cells * resolution_m)
        dy = (z[2 * cells:, cells:-cells] - z[:-2 * cells, cells:-cells]) / (2 * cells * resolution_m)
        s = np.degrees(np.arctan(np.hypot(dx, dy)))
        baseline = 2 * cells * resolution_m
        baselines[f"{baseline:g}"] = {"baseline_m": baseline, "max_deg": float(s.max()),
                                      "p95_deg": float(np.percentile(s, 95)),
                                      "sample_count": int(s.size), "border_excluded_cells": cells}
    return {
        "post_spacing_m": resolution_m, "height_range_m": float(np.ptp(z)),
        "triangle_slope_upper_bound_deg": float(triangle_max.max()),
        "quads_with_any_candidate_triangle_over_15deg_percent": float(100 * np.mean(triangle_max > 15)),
        "central_difference_slopes": baselines,
        "heightfield_is_2_5d": True, "wheel_scale_obstacles_validated": False,
        "interpretation": "Slopes depend on baseline and triangulation; no vehicle-safe route is certified.",
    }


def _source_comparison(manifest, heights, source):
    import rasterio
    from rasterio.windows import Window
    from pyproj import Transformer
    from .geospatial import mars_crs

    grid = manifest["grid"]
    target = mars_crs(grid["crs_wkt"])
    r = grid["resolution_m"]
    xx, yy = np.meshgrid(grid["projected_origin_m"][0] + np.arange(grid["width"]) * r,
                         grid["projected_origin_m"][1] + np.arange(grid["height"]) * r)
    with rasterio.open(source) as ds:
        mars_crs(ds.crs.to_wkt())
        if not ds.crs or ds.count != 1 or ds.transform.b or ds.transform.d:
            raise ValueError("Source comparison requires the original north-up single-band DEM")
        if list(ds.transform)[:6] != manifest["source"]["raster_transform"]:
            raise ValueError("Source transform differs from the recorded original DEM")
        sx, sy = Transformer.from_crs(target, ds.crs, always_xy=True).transform(xx, yy)
        columns = (sx - ds.transform.c) / ds.transform.a - 0.5
        rows = (sy - ds.transform.f) / ds.transform.e - 0.5
        if (columns.min() < -1e-7 or rows.min() < -1e-7 or
                columns.max() > ds.width - 1 + 1e-7 or rows.max() > ds.height - 1 + 1e-7):
            raise ValueError("Source does not cover every output height post")
        columns, rows = np.clip(columns, 0, ds.width - 1), np.clip(rows, 0, ds.height - 1)
        ic = np.minimum(np.floor(columns).astype(int), ds.width - 2)
        ir = np.minimum(np.floor(rows).astype(int), ds.height - 2)
        c0, r0, c1, r1 = int(ic.min()), int(ir.min()), int(ic.max()) + 2, int(ir.max()) + 2
        raw = ds.read(1, window=Window(c0, r0, c1 - c0, r1 - r0), masked=True).astype("float64")
        if np.ma.getmaskarray(raw).any() or not np.isfinite(raw).all():
            raise ValueError("Source comparison includes NoData")
        raw = np.asarray(raw) * ds.scales[0] + ds.offsets[0]
        dc, dr = columns - ic, rows - ir
        ic, ir = ic - c0, ir - r0
        sampled = ((1 - dr) * ((1 - dc) * raw[ir, ic] + dc * raw[ir, ic + 1]) +
                   dr * ((1 - dc) * raw[ir + 1, ic] + dc * raw[ir + 1, ic + 1]))
    error = np.abs(sampled - (heights + manifest["vertical_datum_offset_m"]))
    if float(error.max()) > 2e-6:
        raise ValueError(f"Source/converted heights differ: maximum {error.max():.9g} m")
    fingerprint = None
    local = Path(source)
    if local.is_file():
        with local.open("rb") as stream:
            fingerprint = hashlib.file_digest(stream, "sha256").hexdigest()
        expected = manifest["source"].get("attribution", {}).get("source_file_sha256")
        if expected and fingerprint != expected:
            raise ValueError("Source file SHA-256 differs from recorded official source")
    return {"sample_count": int(error.size), "max_abs_error_m": float(error.max()),
            "rmse_m": float(np.sqrt(np.mean(error ** 2))), "tolerance_m": 2e-6,
            "source_file_sha256": fingerprint,
            "method": "inverse CRS transform and independent four-source-post bilinear interpolation",
            "is_ground_truth_accuracy_measurement": False}


def audit_bundle(manifest_path, *, source_dem=None):
    path = Path(manifest_path).resolve()
    spec = importlib.util.spec_from_file_location("mare_fidelity_validator", ROOT / "Content/Python/mars_setup.py")
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    manifest, _ = validator.load_bundle(path)
    z = np.loadtxt(path.parent / "elevation.csv")
    layout, grid = manifest["landscape"], manifest["grid"]
    encoded = np.fromfile(path.parent / "heightmap.r16", dtype="<u2").reshape(layout["height"], layout["width"])
    decoded = np.fliplr(encoded).astype("float64")[:grid["height"], :grid["width"]] * manifest["vertical_quantization_m"]
    error = np.abs(decoded - z)
    image = manifest.get("imagery", {})
    return {
        "schema_version": 1, "region": manifest["region"], "extent_m": grid["extent_m"],
        "bundle_manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source_documents_verified": sorted(manifest.get("source_documents", {})),
        "source_comparison": _source_comparison(manifest, z, source_dem) if source_dem else None,
        "heightfield_encoding": {"post_count": int(z.size), "max_abs_error_m": float(error.max()),
                                  "quantization_step_m": manifest["vertical_quantization_m"],
                                  "is_source_accuracy": False},
        "terrain": terrain_metrics(z, grid["resolution_m"]),
        "imagery": {"registered": bool(image), "grayscale_reference": bool(image),
                    "texture_sample_spacing_m": [extent / pixels for extent, pixels in
                                                 zip(grid["extent_m"], (image["width"], image["height"]))]
                    if image else None, "source_accuracy_measured": False},
        "source_quality": {"crop_effective_resolution_m": None, "per_post_height_uncertainty_m": None,
                           "absolute_geodetic_accuracy_m": None,
                           "edited_or_interpolated_area_mask_available": False},
        "engine_collision_verified": False, "photometry_validated": False,
        "wheel_soil_physics_validated": False,
        "limits": ["An orthoimage does not supply 3D rock geometry or hidden crater floors.",
                   "Posting/quantization are not effective resolution or stereo/datum accuracy.",
                   "Source stereo products include manual editing/interpolation; no per-post confidence mask is bundled.",
                   "A heightfield cannot represent caves, overhangs or deformable soil.",
                   "Small pits, rocks, steps and loose regolith need additional measured rover-scale data.",
                   "This offline report never substitutes for native engine collision and render acceptance."],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "Content/Mars/Jezero/manifest.json")
    parser.add_argument("--source-dem", help="Optional original local/HTTP GeoTIFF for a dense independent audit")
    parser.add_argument("--output", type=Path, help="New JSON report; existing files are not overwritten")
    args = parser.parse_args(argv)
    try:
        report = audit_bundle(args.manifest, source_dem=args.source_dem)
        output = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(output)
        else:
            print(output, end="")
    except (OSError, ValueError) as error:
        parser.exit(1, f"Fidelity audit failed: {error}\n")


if __name__ == "__main__":
    main()
