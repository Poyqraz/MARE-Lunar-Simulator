"""Terrain planning must preserve hazards, metric scale and real goal positions."""

import importlib
import math

import numpy as np
import pytest


def planning():
    return importlib.import_module("mars_rover.planning")


def test_route_goes_around_a_crater_and_never_fills_unknown_data():
    p = planning()
    heights = np.zeros((25, 25))
    heights[8:17, 8:17] = -3
    heights[4:7, 10] = np.nan
    grid = p.TerrainMap(heights, 1, p.PlanningLimits(robot_radius_m=0.4))
    route = grid.plan((3, 12), (21, 12))
    assert route[0] == (3.0, 12.0) and route[-1] == (21.0, 12.0)
    assert max(abs(y - 12) for x, y in route) >= 6
    assert grid.blocked[5, 10]
    assert all(grid.segment_clear(a, b) for a, b in zip(route, route[1:]))


def test_footprint_closes_a_gap_that_a_point_robot_would_enter():
    p = planning()
    z = np.zeros((15, 15))
    valid = np.ones_like(z, dtype=bool)
    valid[:, 7] = False
    valid[7, 7] = True
    point = p.TerrainMap(z, 1, p.PlanningLimits(robot_radius_m=0), valid=valid)
    assert point.plan((3, 7), (11, 7))
    rover = p.TerrainMap(z, 1, p.PlanningLimits(robot_radius_m=0.6), valid=valid)
    with pytest.raises(p.NoRoute):
        rover.plan((3, 7), (11, 7))


def test_diagonal_corner_cutting_is_not_a_path():
    p = planning()
    grid = p.TerrainMap(np.zeros((5, 5)), 1, p.PlanningLimits(robot_radius_m=0))
    grid.blocked[1, 2] = grid.blocked[2, 1] = True
    assert not grid.segment_clear((1, 1), (2, 2))


def test_exact_goal_is_preserved_and_outside_or_blocked_goal_is_rejected():
    p = planning()
    grid = p.TerrainMap(np.zeros((10, 10)), 1, p.PlanningLimits(robot_radius_m=0))
    assert grid.plan((2.2, 2.1), (7.3, 7.2))[-1] == (7.3, 7.2)
    for goal in [(20, 20), (float("nan"), 3), (0, 0)]:
        with pytest.raises((ValueError, p.NoRoute)):
            grid.plan((2, 2), goal)


def test_replan_near_goal_does_not_reverse_toward_start_cell_center():
    p = planning()
    grid = p.TerrainMap(np.zeros((10, 10)), 1, p.PlanningLimits(robot_radius_m=0))
    start, goal = (5.01225, 4.58223), (5.0, 4.0)
    route = grid.plan(start, goal)
    assert route == [start, goal]
    assert grid.segment_clear(*route)


def test_replan_in_goal_cell_connects_exact_start_directly_to_goal():
    p = planning()
    grid = p.TerrainMap(np.zeros((10, 10)), 1, p.PlanningLimits(robot_radius_m=0))
    start, goal = (5.1, 4.4), (5.1, 4.1)
    route = grid.plan(start, goal)
    assert route == [start, goal]
    assert grid.segment_clear(*route)


def test_shortening_start_connection_never_crosses_blocked_terrain():
    p = planning()
    grid = p.TerrainMap(np.zeros((10, 10)), 1, p.PlanningLimits(robot_radius_m=0))
    grid.blocked[4, 5] = True
    start, goal = (5.01225, 5.58223), (5.0, 3.0)
    route = grid.plan(start, goal)
    assert route[0] == start and route[-1] == goal
    assert all(grid.segment_clear(a, b) for a, b in zip(route, route[1:]))


def test_triangle_slope_catches_a_pit_that_central_gradient_misses():
    p = planning()
    z = np.zeros((9, 9))
    z[4, 4] = -1
    grid = p.TerrainMap(z, 1, p.PlanningLimits(robot_radius_m=0))
    assert grid.slope_deg[4, 4] > 45
    assert grid.blocked[4, 4]


def test_reference_jezero_route_uses_the_shipped_metric_grid():
    p = planning()
    grid = p.TerrainMap.from_bundle()
    route = grid.plan((126, 126), (200, 100))
    assert route[-1] == (200.0, 100.0)
    assert all(grid.segment_clear(a, b) for a, b in zip(route, route[1:]))
    assert sum(math.dist(a, b) for a, b in zip(route, route[1:])) >= math.hypot(74, 26)


def test_small_observed_positive_and_negative_hazards_block_the_route():
    p = planning()
    grid = p.TerrainMap(np.zeros((20, 20)), 1, p.PlanningLimits(robot_radius_m=0.3))
    result = grid.observe(np.array([[10.1, 10.2, 0.3], [12.1, 10.2, -0.4], [8, 8, 0], [np.nan, 1, 1]]))
    assert result["positive_obstacles"] == 1
    assert result["negative_obstacles"] == 1
    assert grid.blocked[10, 10] and grid.blocked[10, 12]
    assert not grid.blocked[8, 8]
    # A no-return is not evidence that an obstacle has gone away.
    grid.observe(np.full((10, 3), np.nan))
    assert grid.blocked[10, 10]


def test_observation_preserves_edge_points_and_strict_hazard_thresholds():
    p = planning()
    grid = p.TerrainMap(np.zeros((6, 6)), 1, p.PlanningLimits(robot_radius_m=0))
    points = np.array([
        [1, 1, 0],
        [2, 2, np.nextafter(0.15, np.inf)],
        [2, 3, np.nextafter(-0.15, -np.inf)],
        [3, 3, 0.15],
        [3, 2, -0.15],
        [5, 5, 0.25],
        [0, 2, -0.25],
        [np.nextafter(0.0, -np.inf), 3, 0.5],
        [np.nextafter(5.0, np.inf), 1, 0.5],
        [1, np.nan, 1],
        [1, 1, np.nan],
        [np.inf, 2, 2],
    ])
    first = grid.observe(points)
    assert first["valid_inside_points"] == 7
    assert first["positive_obstacles"] == first["negative_obstacles"] == 2
    assert first["map_changed"] is True
    assert grid.raw_blocked[2, 2] and grid.raw_blocked[3, 2]
    assert not grid.raw_blocked[3, 3] and not grid.raw_blocked[2, 3]
    second = grid.observe(points)
    assert second["map_changed"] is False
