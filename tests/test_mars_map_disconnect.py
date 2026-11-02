import copy

import numpy as np
import pytest

from mars_rover.planning import PlanningLimits, TerrainMap
from tools.analyze_mars_map_disconnect import IncompleteEvidence, analyze


@pytest.fixture
def wall_record():
    grid = TerrainMap(np.zeros((11, 11)), 1, PlanningLimits(robot_radius_m=0))
    grid.manifest_sha256 = "a" * 64
    cells = [{"cell_row_col": [row, 5]} for row in range(1, 10)]
    stamp = "1700000000000000000"
    export = {
        "terrain_manifest_sha256": grid.manifest_sha256,
        "missions": [{"mission_id": "mission", "status": "blocked",
                      "error": "No connected traversable route to the requested goal",
                      "end_pose": {"stamp_ns": stamp, "position_m": [2, 5, 0]}, "goal": [8, 5]}],
        "obstacle_diagnostics": {
            "enabled": True, "frames_evicted": 0,
            "last_planning_failure": {
                "mission_id": "mission", "stamp_ns": stamp, "map_revision": 1,
                "error": "No connected traversable route to the requested goal",
                "start": {"cell_row_col": [5, 2], "blocked": False},
                "goal": {"cell_row_col": [5, 8], "blocked": False},
            },
            "frames": [{"map_revision": 1, "source": "lidar", "new_cells_total": len(cells),
                        "new_cells_truncated": 0, "new_cells": cells}],
        },
    }
    return grid, export


def test_rebuilds_disconnect_and_compares_sources_without_mutating_map(wall_record):
    grid, export = wall_record
    before = grid.raw_blocked.copy()
    result = analyze(export, grid)
    assert result["recorded_failure"]["route_found"] is False
    assert result["static_terrain_only"]["route_found"] is True
    assert result["without_recorded_lidar_cells"]["route_found"] is True
    assert result["without_recorded_ground_truth_cells"]["route_found"] is False
    assert result["recorded_cells_by_source"] == {"lidar": 9, "ground_truth": 0, "stereo": 0}
    assert np.array_equal(grid.raw_blocked, before)


def test_includes_cells_from_other_missions_and_compares_both_sources(wall_record):
    grid, export = wall_record
    diag = export["obstacle_diagnostics"]
    first = diag["frames"][0]
    cells = first["new_cells"]
    first.update(mission_id="an-earlier-mission", new_cells=cells[:5], new_cells_total=5)
    diag["frames"].append({"map_revision": 2, "source": "ground_truth", "new_cells_total": 4,
                           "new_cells_truncated": 0, "new_cells": cells[5:]})
    diag["last_planning_failure"]["map_revision"] = 2
    result = analyze(export, grid)
    assert result["without_recorded_lidar_cells"]["route_found"] is True
    assert result["without_recorded_ground_truth_cells"]["route_found"] is True
    assert result["recorded_cells_by_source"]["lidar"] == 5
    assert result["recorded_cells_by_source"]["ground_truth"] == 4


def test_offline_image_displays_recorded_wall_and_never_overwrites(wall_record, tmp_path):
    from PIL import Image

    grid, export = wall_record
    before = grid.blocked.copy()
    path = tmp_path / "replay.png"
    result = analyze(export, grid, image_path=path)
    assert result["image_path"] == str(path)
    assert result["recorded_failure"]["route_found"] is False
    image = Image.open(path).convert("RGB")
    r, g, b = image.getpixel((5 * 4 + 2, 5 * 4 + 2))
    assert r > 200 and g > 150 and b < 150  # The recorded LiDAR wall remains drawn.
    assert np.array_equal(grid.blocked, before)
    content = path.read_bytes()
    repeated = analyze(export, grid, image_path=path)
    assert repeated["status"] == "reconstructed" and repeated["image_error"]
    assert path.read_bytes() == content


def test_selected_lidar_samples_are_counted_without_claiming_full_scan_statistics(wall_record):
    grid, export = wall_record
    cells = export["obstacle_diagnostics"]["frames"][0]["new_cells"]
    cells[0].update(sample_residual_m=0.2, hazard_points=1)
    cells[1].update(sample_residual_m=-0.4, hazard_points=4)
    summary = analyze(export, grid)["selected_lidar_samples"]
    assert summary["recorded_lidar_cells"] == 9 and summary["samples_with_residual"] == 2
    assert summary["positive_samples"] == summary["negative_samples"] == 1
    assert summary["median_residual_m"] == pytest.approx(-0.1)
    assert summary["cells_with_hazard_point_counts"] == 2 and summary["cells_with_one_hazard_point"] == 1
    assert "not a representative sample" in summary["limits"]


@pytest.mark.parametrize("defect", ["wrong_manifest", "frames_evicted", "missing_revision", "truncated",
                                    "missing_cell", "duplicate_cell", "existing_cell", "bad_stamp",
                                    "wrong_failure", "mismatched_goal", "different_planner_result"])
def test_incomplete_or_inconsistent_evidence_never_produces_a_counterfactual(wall_record, defect):
    grid, original = wall_record
    export = copy.deepcopy(original)
    diag = export["obstacle_diagnostics"]
    failure = diag["last_planning_failure"]
    frame = diag["frames"][0]
    if defect == "wrong_manifest":
        export["terrain_manifest_sha256"] = "b" * 64
    elif defect == "frames_evicted":
        diag["frames_evicted"] = 1
    elif defect == "missing_revision":
        failure["map_revision"] = 2
    elif defect == "truncated":
        frame["new_cells_truncated"] = 1
    elif defect == "missing_cell":
        frame["new_cells"].pop()
    elif defect == "duplicate_cell":
        frame["new_cells"][-1] = copy.deepcopy(frame["new_cells"][0])
    elif defect == "existing_cell":
        frame["new_cells"][0] = {"cell_row_col": [0, 5]}
    elif defect == "bad_stamp":
        failure["stamp_ns"] = "1700000000000000001"
    elif defect == "wrong_failure":
        failure["mission_id"] = "another-mission"
    elif defect == "mismatched_goal":
        failure["goal"]["cell_row_col"] = [8, 5]
    elif defect == "different_planner_result":
        failure["start"]["blocked"] = True
    with pytest.raises(IncompleteEvidence):
        analyze(export, grid, "mission")
