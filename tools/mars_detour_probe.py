"""Read-only route preview and opt-in supervised drive around a known obstacle.

Default mode never sends a command: it runs the CPU LiDAR short-probe preflight
(stationary rover, fresh pose/sensors, same session twice, map revision match),
rebuilds the planner on the live inflated /map with this checkout's planner
code and prints MARS_ROTA_ONIZLEME.

--send sends one goal and a stop only when the preflight is repeated and the
current session and map revision equal the values the operator copied from the
preview. During motion it stops on session/mission change, stale pose, lost CPU
LiDAR, any replan, route-derived distance/time bounds or cross-track deviation.
Synchronous HTTP polling is not real-time control, and a route on the inflated
grid is not proof of a collision-free or fully observed corridor.
"""

import argparse
import copy
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mars_rover.planning import NoRoute, TerrainMap  # noqa: E402
from tools import mars_cpu_lidar_short_probe as short  # noqa: E402

FOLLOW_SPEED_M_S = 0.15  # RouteFollower default in mars_rover/navigation.py
# shortcut: fixed test bound near the 0.6 m footprint margin, not a measured
# vehicle capability; revisit after native cross-track logs exist.
MAX_CROSS_TRACK_M = 0.75
MAX_DURATION_S = 300.0


def live_terrain(static, snapshot, grid):
    """Return a planner on the service's inflated live grid, failing closed on any mismatch."""
    if snapshot.get("terrain_manifest_sha256") != static.manifest_sha256:
        raise ValueError("Servisin arazi manifesti bu checkout'taki paketle eslesmiyor")
    h, w = static.heights.shape
    blocked = grid.get("blocked")
    if (grid.get("width") != w or grid.get("height") != h or grid.get("resolution_m") != static.resolution_m
            or not isinstance(blocked, list) or len(blocked) != w * h):
        raise ValueError("Canli harita boyutu veya cozunurlugu statik paketle eslesmiyor")
    live = np.asarray(blocked, dtype=np.int64).reshape(h, w) != 0
    # Every static terrain block must already be in the live grid; otherwise the
    # service used another bundle or vehicle limits and the preview is invalid.
    if np.any(static.blocked & ~live):
        raise ValueError("Canli haritada statik arazi engelleri eksik: farkli paket veya arac limitleri")
    trial = copy.copy(static)
    trial.blocked = live
    return trial


def preview(static, context, goal):
    """Plan exactly as the service would on the current live map; send nothing."""
    snapshot = context["snapshot"]
    prefer_direct = snapshot.get("short_direct_route_enabled") is True
    trial = live_terrain(static, snapshot, context["grid"])
    start = tuple(float(v) for v in context["position_m"][:2])
    try:
        route = trial.plan(start, goal, prefer_short_direct=prefer_direct)
    except NoRoute as error:
        raise ValueError(f"Canli haritada rota yok: {error}") from error
    length = sum(math.dist(a, b) for a, b in zip(route, route[1:]))
    direct_open = trial.segment_clear(start, goal)
    return {
        "session_id": context["session_id"],
        "map_revision": context["map_revision"],
        "start_m": [round(v, 3) for v in start],
        "goal_m": list(goal),
        "route_m": [[round(x, 3), round(y, 3)] for x, y in route],
        "route_length_m": round(length, 3),
        "straight_distance_m": round(math.dist(start, goal), 3),
        "direct_segment_open": direct_open,
        # Planner-only label: a detour exists because the inflated live map
        # closes the straight segment, not because an obstacle was verified.
        "test_type": "open_direct_route" if direct_open else "pre_existing_obstacle_detour",
        "short_direct_route_enabled": prefer_direct,
        "dynamic_inflated_cells": int(np.count_nonzero(trial.blocked & ~static.blocked)),
    }


def goal_chooser(static, goal, *, expect_session=None, expect_map_revision=None):
    def choose(context):
        if expect_session is not None and (context["session_id"] != expect_session
                                           or context["map_revision"] != expect_map_revision):
            raise ValueError("Oturum veya harita revizyonu onizlemeden farkli; once yeniden onizleme yapin")
        result = preview(static, context, goal)
        length = result["route_length_m"]
        return {
            "goal_m": goal,
            "details": {k: result[k] for k in ("route_length_m", "direct_segment_open", "test_type")},
            "preview": result,
            "route_m": [tuple(p) for p in result["route_m"]],
            "max_cross_track_m": MAX_CROSS_TRACK_M,
            "limits": {"duration_s": min(MAX_DURATION_S, 2 * length / FOLLOW_SPEED_M_S + 20.0),
                       "displacement_m": length + 0.5, "sampled_path_m": 1.3 * length + 1.0},
        }
    return choose


def main(argv=None, *, get=short.common._get, post=short.common._post, log=print):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--goal", nargs=2, type=float, required=True, metavar=("X_M", "Y_M"),
                        help="Mars local grid goal in metres (x east, y north)")
    parser.add_argument("--manifest", type=Path, help="Bundle manifest; default is the bundled Jezero manifest")
    parser.add_argument("--send", action="store_true", help="Send the goal after repeating the preflight")
    parser.add_argument("--expect-session", help="session_id printed by the read-only preview (required with --send)")
    parser.add_argument("--expect-map-revision", type=int, help="map_revision printed by the preview")
    args = parser.parse_args(argv)
    if not all(math.isfinite(v) for v in args.goal):
        parser.error("--goal must be finite")
    if args.send and (not args.expect_session or args.expect_map_revision is None):
        parser.error("--send requires --expect-session and --expect-map-revision from a fresh preview")
    goal = (args.goal[0], args.goal[1])
    try:
        static = TerrainMap.from_bundle(args.manifest)
        if not args.send:
            ready = short._wait_for_preflight(get, now=time.monotonic, sleep=time.sleep, log=log,
                                              choose_goal=goal_chooser(static, goal))
            log("MARS_ROTA_ONIZLEME: " + json.dumps(ready["preview"], ensure_ascii=False, allow_nan=False))
            log("Hedef gonderilmedi (salt okunur onizleme).")
            return ready["preview"]
        chooser = goal_chooser(static, goal, expect_session=args.expect_session,
                               expect_map_revision=args.expect_map_revision)
        summary = short.run(get=get, post=post, log=log, choose_goal=chooser)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit("ON_KONTROL_BASARISIZ: " + str(error) + "; hedef gonderilmedi.") from error
    log("MARS_ENGEL_DOLASMA: " + json.dumps(summary, ensure_ascii=False, allow_nan=False))
    if not summary["stop_request_succeeded"]:
        raise SystemExit("DURDURMA ISTEGI BASARISIZ: Unreal'da Stop dugmesine basin")
    if not summary["goal_confirmed"]:
        raise SystemExit("HEDEF YANITI BELIRSIZ: Unreal'da Stop dugmesini kontrol edin")
    return summary


if __name__ == "__main__":
    main()
