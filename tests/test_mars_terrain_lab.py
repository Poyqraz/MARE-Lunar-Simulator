"""Jezero terrain lab: synthetic rock layout, rock placement maths and the free-fall gravity fit."""
import json
import math
import sys
import types
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Content/Python"))
sys.modules.setdefault("unreal", types.ModuleType("unreal"))

import mars_physics_probe as probe  # noqa: E402
import mars_rock_scenario as placement  # noqa: E402
from mars_rover import rock_scenario  # noqa: E402


def flat(size=60, slope_deg=0.0):
    x = np.arange(size, dtype=float)
    return np.tile(x * math.tan(math.radians(slope_deg)), (size, 1))


def test_layout_is_reproducible_and_sized_from_the_rover():
    a = rock_scenario.generate(flat(), 1.0, (20, 30), -98.18)
    b = rock_scenario.generate(flat(), 1.0, (20, 30), -98.18)
    assert a == b
    heights = {r["class"]: r["exposed_height_m"] for r in a["rocks"]}
    wheel = rock_scenario.ROVER["wheel_radius_m"]
    assert heights["pebble"] == pytest.approx(0.5 * wheel, abs=1e-4)
    assert heights["pebble"] < heights["belly"] < 0.15 < heights["threshold"] < heights["blocker"]
    assert "NOT measured" in a["notice"] and a["kind"] == "synthetic_rock_test"


def test_detour_rock_lies_on_the_heading_between_start_and_goal():
    s = rock_scenario.generate(flat(), 1.0, (20, 30), -90.0)  # facing south
    start = np.array([20.0, 30.0])
    goal = np.array(s["detour_goal_xy_m"])
    assert goal == pytest.approx(start + [0, -12], abs=1e-6)
    blocker = np.array(next(r for r in s["rocks"] if r["id"] == "detour_blocker")["center_xy_m"])
    assert np.linalg.norm(blocker - (start + [0, -6])) <= 0.3


def test_layout_refuses_steep_ground():
    with pytest.raises(ValueError, match="deg terrain"):
        rock_scenario.generate(flat(slope_deg=10), 1.0, (20, 30), 0.0)


def test_cli_never_overwrites(tmp_path):
    bundle = tmp_path / "b"
    bundle.mkdir()
    np.savetxt(bundle / "elevation.csv", flat())
    (bundle / "manifest.json").write_text(json.dumps({"grid": {"resolution_m": 1.0}}))
    out = tmp_path / "rocks.json"
    rock_scenario.main(["--manifest", str(bundle / "manifest.json"), "--start", "20", "30", "--output", str(out)])
    assert json.loads(out.read_text())["manifest_sha256"]
    with pytest.raises(SystemExit):
        rock_scenario.main(["--manifest", str(bundle / "manifest.json"), "--start", "20", "30", "--output", str(out)])


def test_placement_puts_exactly_the_exposed_height_above_ground():
    rock = {"exposed_height_m": 0.3012, "size_m": [0.56, 0.53, 0.4303]}
    centre = placement.center_height_m(10.0, rock)
    assert centre + rock["size_m"][2] / 2 - 10.0 == pytest.approx(0.3012)
    assert placement.ue_location(2.0, 3.0, 1.0) == (-200.0, 300.0, 100.0)


def test_free_fall_fit_recovers_gravity_and_ignores_the_bounce():
    g, dt = 3.71, 1 / 30
    samples, z, v = [], 20.0, -1.0
    for i in range(120):
        t = i * dt
        samples.append((t, z, 0.0))
        z, v = z + v * dt - 0.5 * g * dt * dt, v - g * dt
        if z < 0.1:  # bounce off the ground, as the native probe does
            z, v = 0.1 + (0.1 - z), -v * 0.5
    fall = probe.free_fall_part(samples, 0.1)
    fit = probe.fit_free_fall(fall)
    assert fit["g_m_s2"] == pytest.approx(g, rel=1e-6)
    assert len(fall) < len(samples)


def _vicar(path, xyz, frame="SITE_FRAME", kind="XYZ_FILTER_MAP"):
    nb, nl, ns = xyz.shape
    body = (f"FORMAT='REAL' ORG='BSQ' NL={nl} NS={ns} NB={nb} NBB=0 EOL=0 REALFMT='IEEE' "
            f"PROPERTY='DERIVED_IMAGE_PARMS' DERIVED_IMAGE_TYPE='{kind}' "
            f"REFERENCE_COORD_SYSTEM_NAME='{frame}' REFERENCE_COORD_SYSTEM_INDEX=(23) ")
    size = 1024
    label = (f"LBLSIZE={size} " + body).ljust(size).encode("latin-1")
    path.write_bytes(b"PDS_VERSION_ID = PDS3 ".ljust(512) + label + xyz.astype(">f4").tobytes())


def test_xyz_summary_reports_its_own_frame_and_never_places_points(tmp_path):
    from mars_rover import m2020_xyz

    xyz = np.zeros((3, 2, 3))
    xyz[:, 0, :] = [[1, 2, 3], [4, 5, 6], [-1, -2, -3]]  # second line stays (0,0,0) = invalid
    _vicar(tmp_path / "x.IMG", xyz)
    s = m2020_xyz.summarize(tmp_path / "x.IMG")
    assert s["reference_frame"] == {"name": "SITE_FRAME", "index": "23"}
    assert s["valid_fraction"] == 0.5 and s["min_m"] == [1, 4, -3] and s["placed_on_terrain"] is False
    _vicar(tmp_path / "r.IMG", xyz, kind="RANGE_MAP")
    with pytest.raises(ValueError, match="XYZ"):
        m2020_xyz.summarize(tmp_path / "r.IMG")
