"""Create a NEW Mars level from a prepared DEM bundle, with Play stopped.

In Unreal's Python console:
    import mars_setup
    mars_setup.build()  # bundled, measured 252 x 252 m Jezero starter terrain

No NumPy/rasterio is needed inside Unreal. Does not edit the lunar levels,
Blueprint graphs, physics tuning or shared ground-truth mask materials.
"""
from array import array
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

_PENDING = {}


def load_bundle(manifest_path):
    path = Path(manifest_path).resolve()
    m = json.loads(path.read_text(encoding="utf-8"))
    if m.get("schema_version") != 1 or m.get("planet") != "mars":
        raise ValueError("Expected schema 1 Mars bundle")
    required = {"heightmap.r16", "elevation.csv", "soil.csv"}
    documents = m.get("source_documents", {})
    if not isinstance(documents, dict) or not set(documents) <= {"source_dem.xml", "source_ortho.xml"}:
        raise ValueError("Unsupported source metadata files")
    required.update(documents)
    if "imagery" in m:
        if not isinstance(m["imagery"], dict) or m["imagery"].get("filename") != "ortho_reference.png":
            raise ValueError("Invalid registered imagery filename")
        required.add("ortho_reference.png")
    if set(m.get("files", {})) != required:
        raise ValueError("Bundle files disagree with the supported terrain/imagery schema")
    for filename, description in m["files"].items():
        if hashlib.sha256((path.parent / filename).read_bytes()).hexdigest() != description["sha256"]:
            raise ValueError(f"Bundle hash mismatch: {filename}")
    layout, grid = m["landscape"], m["grid"]
    keys = ("section_size", "sections_per_component", "component_count_x", "component_count_y", "width", "height")
    if any(type(layout[k]) is not int or layout[k] <= 0 for k in keys):
        raise ValueError("Invalid integer Landscape layout")
    if layout["section_size"] not in (63, 127, 255) or layout["sections_per_component"] not in (1, 2):
        raise ValueError("Unsupported Landscape layout")
    q = layout["section_size"] * layout["sections_per_component"]
    if (layout["width"] != q * layout["component_count_x"] + 1 or
            layout["height"] != q * layout["component_count_y"] + 1 or
            layout["component_count_x"] * layout["component_count_y"] > 1024 or
            max(layout["width"], layout["height"]) > 4097):
        raise ValueError("Landscape dimensions do not match the layout")
    if not (3 <= grid["width"] <= layout["width"] and 3 <= grid["height"] <= layout["height"]):
        raise ValueError("Invalid source grid dimensions")
    numbers = [*layout["scale"], *layout["location_cm"], grid["resolution_m"], m["gravity_m_s2"],
               m["vertical_datum_offset_m"]]
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in numbers):
        raise ValueError("Non-finite bundle geometry")
    if len(layout["scale"]) != 3 or len(layout["location_cm"]) != 3 or min(layout["scale"]) <= 0:
        raise ValueError("Landscape scales must be positive")
    r = grid["resolution_m"]
    if r <= 0 or not 0 < m["gravity_m_s2"] < 20:
        raise ValueError("Invalid resolution/gravity")
    if (grid.get("row_direction") != "north" or grid.get("column_direction") != "east" or
            grid.get("extent_m") != [(grid["width"] - 1) * r, (grid["height"] - 1) * r]):
        raise ValueError("Grid directions or extent disagree with the coordinate contract")
    if (not math.isclose(layout["scale"][0], r * 100) or
            not math.isclose(layout["scale"][1], r * 100) or
            not math.isclose(layout["location_cm"][0], -(layout["width"] - 1) * r * 100) or
            layout["location_cm"][1] != 0):
        raise ValueError("Landscape and planner coordinate scales disagree")
    expected = array("H")
    expected.frombytes((path.parent / "heightmap.r16").read_bytes())
    if sys.byteorder != "little":
        expected.byteswap()
    if len(expected) != layout["width"] * layout["height"]:
        raise ValueError("Wrong heightmap byte count")
    quantization = m["vertical_quantization_m"]
    if (type(quantization) not in (int, float) or not math.isfinite(quantization) or quantization <= 0 or
            not math.isclose(layout["scale"][2] / 12800, quantization, rel_tol=1e-9) or
            not math.isclose(layout["location_cm"][2], 32768 * layout["scale"][2] / 128, rel_tol=1e-9)):
        raise ValueError("Inconsistent vertical height encoding")
    # Hashes alone do not catch a corrupted transform in the manifest itself.
    with (path.parent / "elevation.csv").open(encoding="utf-8") as handle:
        count = 0
        for row, line in enumerate(handle):
            values = [float(v) for v in line.split()]
            if row >= grid["height"] or len(values) != grid["width"]:
                raise ValueError("Elevation dimensions disagree with height grid")
            for col, value in enumerate(values):
                encoded = expected[row * layout["width"] + layout["width"] - 1 - col]
                decoded = layout["location_cm"][2] / 100 + (encoded - 32768) * quantization
                if not math.isfinite(value) or abs(decoded - value) > quantization + 1e-8:
                    raise ValueError("Elevation and encoded vertical heights disagree")
            count += 1
        if count != grid["height"]:
            raise ValueError("Missing elevation rows")
    if "imagery" in m:
        header = (path.parent / "ortho_reference.png").read_bytes()[:24]
        if (len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or
                struct.unpack(">II", header[16:24]) != (m["imagery"]["width"], m["imagery"]["height"])):
            raise ValueError("Registered imagery dimensions/header disagree")
    return m, expected



def build(manifest_path=None, level_path="/Game/Mars/Jezero", *, rover_blueprint=None,
          spawn_cell=None, preview_material=True, material_path=None, mode="simulation",
          scene_path=None, report_path=None):
    """Create a new Mars environment; optionally include a reference rover.

    mode='orbital_reference' uses the registered unlit grayscale survey image.
    The returned dictionary updates from status='importing' to 'saved'/'failed'
    after deferred verification. Default mode uses illustrative dynamic shading.
    """
    from mars_scene import build_environment
    return build_environment(manifest_path, level_path, load_bundle=load_bundle, pending=_PENDING,
                             rover_blueprint=rover_blueprint, spawn_cell=spawn_cell,
                             preview_material=preview_material, material_path=material_path,
                             mode=mode, scene_path=scene_path, report_path=report_path)
