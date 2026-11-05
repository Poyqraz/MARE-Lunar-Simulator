# Optional direct connection for short routes

`--prefer-short-direct` is an experiment and is disabled by default. The
existing A* plan is always built and validated first. For a goal at most 8 m
away, and an A* result of at most 33 waypoints, the planner may replace the
route by the direct start-to-goal segment if all the following hold:

- The existing inflated-grid segment and diagonal corner checks both pass.
- An identical quarter-cell sampling of each route finds finite terrain.
- The direct segment's sampled slope-weighted 3-D cost is no higher, and its
  sampled peak grid slope is within the existing hard slope limit.

The direct segment can have a higher peak slope than the A* route, even though
its sampled total cost is lower; the flag does not assert a no-steeper route.
Its slope comparison includes adjacent cells at a sampled diagonal crossing.
These are approximations on the existing terrain grid, not exact optimization
of the A* edge costs or rover dynamics. The existing obstacle inflation, unknown
cell checks, speed and sensor freshness gates are unchanged. No observation is
cleared, and the rover must still stop and replan if new obstacles block a route.

The service exposes `short_direct_route_enabled` in status, mission snapshots,
and mission exports so saved runs identify the configuration. Unreal runtime
driving and hazard coverage are not established by Python or offline replay
tests. In particular, 8 m is a bounded candidate size, not proof that the
sensors observed every part of the route.
