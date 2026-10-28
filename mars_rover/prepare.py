"""Prepare real Mars terrain without loading the whole planetary raster.

    python -m mars_rover.prepare --output generated/jezero
    python -m mars_rover.prepare --source local.tif --region jezero --window 3404 7096 253 253 --output generated/custom
"""
import argparse
import json
from pathlib import Path
import urllib.request

from .terrain import prepare_bundle, read_dem
from .geospatial import local_metric_dem
from .imagery import read_ortho


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", type=Path,
                        default=Path(__file__).resolve().parents[1] / "Config/Mars/jezero.json")
    parser.add_argument("--source", help="Local DEM or HTTP GeoTIFF; otherwise use the preset's source")
    parser.add_argument("--window", nargs=4, type=int, metavar=("COL", "ROW", "WIDTH", "HEIGHT"))
    parser.add_argument("--output", type=Path, required=True, help="New, non-existing bundle folder")
    parser.add_argument("--region", help="Region identifier when supplying a different source")
    parser.add_argument("--metric-size", type=int, help="Odd local metric grid size; defaults to preset for its source")
    parser.add_argument("--resolution", type=float, default=1.0, help="Local grid resolution, m")
    parser.add_argument("--ortho-source", help="Aligned single-band orbital orthoimage")
    parser.add_argument("--no-ortho", action="store_true", help="Omit the orbital reference image")
    args = parser.parse_args(argv)
    if args.source and not args.region:
        parser.error("Supply --region when overriding --source; a custom raster is not automatically Jezero")
    preset = json.loads(args.preset.read_text(encoding="utf-8"))
    if preset.get("schema_version") != 1:
        parser.error("Unsupported preset schema")
    source = args.source or preset["source"]
    window = args.window if args.window is not None else (
        None if args.source else preset["window_col_row_width_height"])
    try:
        if args.output.exists():
            raise FileExistsError(f"Output exists: {args.output}; choose a new folder")
        dem = read_dem(source, window=window, vertical_unit=preset["vertical_unit"])
        metric = {"size": args.metric_size, "resolution_m": args.resolution} if args.metric_size else (
            preset.get("local_metric") if not args.source else None)
        if metric:
            dem = local_metric_dem(dem, **metric)
        ortho_source = args.ortho_source or (preset.get("ortho_source") if not args.source else None)
        image = read_ortho(ortho_source, dem, size=preset.get("ortho_size", 1024)) if ortho_source and not args.no_ortho else None
        attribution = preset["attribution"] if not args.source else {
            "note": "Caller-supplied source; verify origin, units and redistribution terms"}
        documents = {}
        for name, uri in preset.get("source_documents", {}).items() if not args.source else ():
            if args.no_ortho and name == "source_ortho.xml":
                continue
            with urllib.request.urlopen(uri, timeout=30) as response:
                documents[name] = {"uri": uri, "content": response.read(1_000_001)}
        path = prepare_bundle(dem, args.output, region=args.region or preset["region"], attribution=attribution,
                              imagery=image, source_documents=documents)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Terrain preparation failed: {error}\n")
    print(f"Prepared {path.resolve()}")
    print("Geometry is measured. Surface materials, soil interaction and rover physics require validation.")
    return path


if __name__ == "__main__":
    main()
