"""Native editor collision probes against decoded terrain posts and grid edges.

This samples collision; it does not verify every triangle, wheel contact,
friction, or a packaged game. No NumPy or other third-party dependency.
"""
import math


def probe_points(manifest, heights):
    grid, layout = manifest["grid"], manifest["landscape"]
    width, height = grid["width"], grid["height"]

    def indices(size):
        result = {1 + round(i * (size - 3) / 8) for i in range(9)}
        section = layout["section_size"]
        seams = range(section, size - 1, section)
        # Include representative subsection/component seams and both sides.
        seams = list(seams)
        for seam in (seams[0], seams[len(seams) // 2], seams[-1]) if seams else ():
            result.update(v for v in (seam - 1, seam, seam + 1) if 0 < v < size - 1)
        return sorted(result)

    rows, cols = indices(height), indices(width)
    cells = {(float(col), float(row)) for row in rows for col in cols}
    # Extrema matter more than a uniform sample on a mostly smooth surface.
    minimum, maximum = (float("inf"), 1, 1), (-float("inf"), 1, 1)
    largest_step = (0, 1, 1, 0, 1)
    for row in range(1, height - 1):
        for col in range(1, width - 1):
            item = (heights[row * layout["width"] + layout["width"] - 1 - col], col, row)
            minimum, maximum = min(minimum, item), max(maximum, item)
            for dc, dr in ((1, 0), (0, 1)):
                if col + dc < width - 1 and row + dr < height - 1:
                    neighbour = heights[(row + dr) * layout["width"] + layout["width"] - 1 - col - dc]
                    largest_step = max(largest_step, (abs(neighbour - item[0]), col, row, dc, dr))
    for _, col, row in (minimum, maximum):
        cells.add((float(col), float(row)))
    _, col, row, dc, dr = largest_step
    cells.update(((float(col), float(row)), (float(col + dc), float(row + dr)),
                  (col + dc / 2, row + dr / 2)))
    # Halfway along an edge is independent of the quad's diagonal convention.
    cells.update((col + 0.5, float(rows[len(rows) // 2])) for col in cols if col + 1 < width)
    cells.update((float(cols[len(cols) // 2]), row + 0.5) for row in rows if row + 1 < height)

    def z(col, row):
        value = heights[row * layout["width"] + layout["width"] - 1 - col]
        return (layout["location_cm"][2] + (value - 32768) * layout["scale"][2] / 128) / 100

    points = []
    for col, row in sorted(cells):
        c, r = int(col), int(row)
        value = z(c, r)
        if col != c:
            value = (value + z(c + 1, r)) / 2
        elif row != r:
            value = (value + z(c, r + 1)) / 2
        points.append((-col * grid["resolution_m"] * 100, row * grid["resolution_m"] * 100, value * 100))
    return points


def verify_landscape(unreal, world, landscape, manifest, heights, *, ignored_actors=None):
    points = probe_points(manifest, heights)
    tolerance_m = 0.002  # numerical trace tolerance, not scientific DEM accuracy
    max_error = 0.0
    for complex_trace in (False, True):
        for x, y, z in points:
            hit = unreal.SystemLibrary.line_trace_single(
                world_context_object=world,
                start=unreal.Vector(x, y, z + 10000), end=unreal.Vector(x, y, z - 10000),
                trace_channel=unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
                trace_complex=complex_trace, actors_to_ignore=ignored_actors or [],
                draw_debug_type=unreal.DrawDebugTrace.NONE, ignore_self=False)
            if hit is None:
                raise RuntimeError(f"Collision trace missed terrain at {(x, y)} (complex={complex_trace})")
            # UE 5.7's reflected HitResult break tuple, in documented field order.
            fields = hit.to_tuple()
            if len(fields) != 18:
                raise RuntimeError("Unsupported native HitResult layout; collision cannot be certified")
            blocking, initial_overlap, point, normal, actor = fields[0], fields[1], fields[5], fields[7], fields[9]
            if blocking is not True or initial_overlap or actor != landscape:
                raise RuntimeError("Collision hit did not belong to the measured Landscape")
            values = (point.x, point.y, point.z, normal.x, normal.y, normal.z)
            if not all(math.isfinite(v) for v in values) or normal.z <= 0:
                raise RuntimeError("Collision returned a non-finite point or invalid surface normal")
            error = max(abs(point.x - x), abs(point.y - y), abs(point.z - z)) / 100
            if error > tolerance_m:
                raise RuntimeError(f"Collision/DEM discrepancy {error:.6g} m exceeds numerical tolerance")
            max_error = max(max_error, error)
    return {"verified": True, "probe_point_count": len(points), "trace_count": 2 * len(points),
            "simple_and_complex": True, "max_abs_position_error_m": max_error,
            "numerical_tolerance_m": tolerance_m, "all_triangles_verified": False,
            "wheel_contact_physics_verified": False,
            "coverage": "interior posts, representative seams, height extrema, largest adjacent height step and edge midpoints"}
