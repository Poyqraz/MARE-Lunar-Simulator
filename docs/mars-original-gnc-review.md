# Original GNC mission control and Mars integration review

Review scope: the original [GNC-Moon-Simulator](https://github.com/raulcastar/GNC-Moon-Simulator)
at `e86ee76c1cc5d14818b893c5f5efd299dd380e9d`, especially its README,
mission-control and planner documentation, rover TCP source, camera scripts,
dashboard HTML and server, configuration and testing instructions. This is a
targeted source review, not a native end-to-end test or an audit of every file
and Unreal Blueprint. The [MARE README](../README.md) already points to GNC;
the dashboard is not contained in a fork of the Unreal project alone.

## What exists upstream

- The ROS 2 Jazzy stack includes global fast-marching planning, a local DWA
  planner, LiDAR obstacle processing, stereo, depth and a web interface. The
  upstream [mission-control documentation](https://github.com/raulcastar/GNC-Moon-Simulator/blob/e86ee76c1cc5d14818b893c5f5efd299dd380e9d/docs/mission-control.md)
  describes a menu on `5000`, overview on `5001`, teleoperation on `5002`,
  camera wall on `5003`, LiDAR/local elevation on `5005`, system on `5006`
  and recording on `5007`.
- The overview displays an interactive map, rover position, goals, routes,
  travelled path, sensor feeds and telemetry. `VIEW` controls follow, orbit
  and top-down Unreal cameras. That top-down camera is a rover-relative game
  view, not a live MRO observation. It does not establish that HiRISE images
  are registered to our Mars terrain.
- The rover node includes acceleration and deceleration ramps. Its skid-steer
  twist interface commands the wheels by side; independent four-motor control
  for the future physical vehicle still needs its own interface and calibration.
- The upstream unit tests use stubs for Unreal and the ROS graph. Upstream also
  documents scenarios that use Unreal in Play. Those facts do not establish
  that this Jezero scene, the user's GPU, UE 5.7.4, locale or a custom rover
  have passed the same scenarios.

## Constraints before a native integration

1. The dashboard is a Flask/Socket.IO frontend backed by ROS 2 nodes, topics,
   services and shared assets. Copying its HTML alone is not an integration.
   A straightforward evaluation uses the upstream ROS stack; a ROS-free
   adapter would have to implement the matching events and data contracts.
2. The upstream ROS bridge and our Python navigation service both use the
   rover TCP port `3003`; the sensor services also use `3004` and `3007`.
   Stop the current navigation service and Play before switching ownership;
   only one controller must command the rover at a time.
3. Our measured local Jezero DEM and its registration, row orientation,
   ENU-to-Unreal transform, scale, sensor mounts and wheel mapping require
   explicit conversion and verification. Upstream planner defaults point to
   lunar elevation and soil CSV files. Do not present those defaults as Mars
   soil or assume the displayed map already matches the UE collision surface.
4. The user's Unreal producer emits Turkish-formatted numbers. Upstream's
   rover `_clean()` strips commas between digits and then uses a standard
   JSON decoder. With captured values, `0,033` becomes invalid JSON `0033`,
   while `37,0` becomes `370`; `-12.600,971` becomes `-12.600971`. Thus
   switching to upstream as-is can lose telemetry or misinterpret it. Prefer
   locale-independent numeric serialization at the producer; an explicitly
   selected Turkish parser can be used for simulation experiments only.
5. Upstream's rover ramp defaults describe its own vehicle and gravity
   settings. Its documentation says a single `/cmd_vel` remains active until
   a zero command. Check stop, stale sensors, stale pose, disconnect, pause,
   controller arbitration and command watchdog independently before driving.
   Do not copy a ramp as a substitute for these checks.
6. Upstream is MIT with stated exceptions: `fast_marching.py`,
   `planner_maps.py` and their tests are derived from GPL-3.0 DyMu. Retain
   attribution and review the applicable licences before redistributing code;
   do not assume the whole stack can be copied as MIT-only source.

## Suggested sequence

1. Repeat the current short drive with capture-age boundary correction and
   record the number and reasons of sensor waits. Do not claim a fix without
   observing the UE run.
2. In a separate, reversible test environment, install and start the original
   GNC stack following its documented WSL2/Docker instructions. Use its own
   lunar reference level first with a single controller and validate stop,
   reconnect, telemetry units and the user's locale.
3. Build a Mars map adapter from the same verified Jezero height data as UE;
   validate independent landmarks, orientation, scale, elevations and
   collision, then feed the resulting map and documented unknown/soil semantics
   into GNC. Confirm sensor extrinsics and goal/pose transforms.
4. Add HiRISE as a separately labelled, registered static map layer, with
   source and resolution shown. Compare landmarks against the DEM; do not
   treat optical texture as measured 3D small rocks, holes or live satellite
   video.
5. On a duplicated Mars level, validate viewport camera switching and restore
   the user's map. Run low-speed short drives, waits, emergency stop, blocked
   goals and sensor-disconnect scenarios. Record evidence before enabling
   longer missions or the custom four-motor rover.
