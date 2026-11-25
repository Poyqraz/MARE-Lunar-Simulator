"""Inspect a Mars 2020 Navcam/Mastcam-Z stereo XYZ product (PDS Imaging Node RDR) without moving it.

    python -m mars_rover.m2020_xyz path/to/NLF_..._XYZ_....IMG --output Saved/Mars/xyz-summary.json

Reports the product's own frame (e.g. SITE_FRAME 23), rover motion counter, units and point
statistics. It deliberately performs no placement: putting points on a terrain bundle needs the
rover pose from the label AND an archived localization (PDS PLACES), and the two solutions can
differ by metres. Data: NASA/JPL-Caltech; cite the Mars 2020 Navcam bundle (DOI 10.17189/x2k7-1v48).
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

import numpy as np

_DTYPES = {("REAL", "IEEE"): ">f4", ("REAL", "RIEEE"): "<f4"}


def read_vicar(path):
    """Return (label dict, array[NB, NL, NS]) for a BSQ VICAR file; an ODL header may precede it."""
    raw = Path(path).read_bytes()
    start = raw.find(b"LBLSIZE=", 0, 1 << 20)
    if start < 0:
        raise ValueError("No VICAR label found")
    size = int(re.match(rb"LBLSIZE=\s*(\d+)", raw[start:]).group(1))
    text = raw[start:start + size].decode("latin-1")
    label = {}
    for key, value in re.findall(r"(\w+)=('(?:[^']|'')*'|\([^)]*\)|[^\s]+)", text):
        label.setdefault(key, value.strip("'"))  # first occurrence: system label and primary task
    nl, ns, nb = (int(label[k]) for k in ("NL", "NS", "NB"))
    if label.get("ORG") != "BSQ" or int(label.get("NBB", 0)) or int(label.get("EOL", 0)):
        raise ValueError("Only BSQ products without binary prefixes or EOL labels are supported")
    dtype = _DTYPES.get((label.get("FORMAT"), label.get("REALFMT")))
    if dtype is None:
        raise ValueError(f"Unsupported sample format {label.get('FORMAT')}/{label.get('REALFMT')}")
    count = nl * ns * nb
    if len(raw) < start + size + count * 4:
        raise ValueError("Truncated VICAR product")
    return label, np.frombuffer(raw, dtype, count, start + size).reshape(nb, nl, ns), text


def summarize(path):
    label, data, text = read_vicar(path)
    if data.shape[0] != 3:
        raise ValueError("An XYZ product has three bands")
    frame = re.search(r"REFERENCE_COORD_SYSTEM_NAME='([^']+)'\s+REFERENCE_COORD_SYSTEM_INDEX=\(?([^)\s]+)", text)
    kind = re.search(r"DERIVED_IMAGE_TYPE='([^']+)'", text)
    if not frame or not kind or "XYZ" not in kind.group(1):
        raise ValueError("Label does not declare an XYZ product with a reference frame")
    xyz = data.astype("float64")
    valid = np.isfinite(xyz).all(axis=0) & ~(xyz == 0).all(axis=0)  # (0,0,0) = missing/invalid
    points = xyz[:, valid]
    blob = Path(path).read_bytes()
    return {
        "file": Path(path).name, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob),
        "derived_image_type": kind.group(1),
        "reference_frame": {"name": frame.group(1), "index": frame.group(2)},
        "units": "m", "axes_note": "SITE/local-level frame: +X north, +Y east, +Z down (Mars 2020 camera SIS)",
        "lines_samples": [int(label["NL"]), int(label["NS"])],
        "valid_fraction": float(valid.mean()),
        "min_m": points.min(axis=1).tolist() if points.size else None,
        "max_m": points.max(axis=1).tolist() if points.size else None,
        "median_m": np.median(points, axis=1).tolist() if points.size else None,
        "placed_on_terrain": False,
        "placement_requirements": "rover pose from this label plus PDS PLACES localization; verify they agree",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("product", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = summarize(args.product)
    text = json.dumps(result, indent=2)
    if args.output:
        if args.output.exists():
            parser.error(f"Output exists: {args.output}")
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
