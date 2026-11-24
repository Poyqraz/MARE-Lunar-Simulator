# Experimental CPU LiDAR capture-pose mode

GPU LiDAR and the existing `LIDR` v1 protocol remain the default. This
opt-in experiment addresses one specific ambiguity: during motion the pose
reported by the rover and the pose used to create a scan may differ even at
the same simulation timestamp. It does not establish the GPU render pose or
solve other sources of terrain and sensor error.

The CPU scanner takes one `FTransform` snapshot, uses its origin and rotation
for its collision line traces, and can send that same transform with the
resulting points. The `LIDR` v2 extension has flags `3`; immediately after the
48-byte v1 header it adds twelve little-endian doubles for a row-major 3x4
sensor-FLU-to-local-map transform. The organized 20-byte point records follow.
The conversion reflects Unreal world X, uses FLU sensor Y left, and converts
centimetres to metres. This is a Mars Python extension, not the ROS wire format.

To use it, set the LiDAR component's `Mode` to CPU and enable
`Send CPU Capture Pose` **before Play**. Restart the navigation service with
`--lidar-pose-source cpu_capture`. An ordinary v1 scan is rejected in this
mode; a v2 scan is rejected in the default telemetry mode. The service still
requires the same fresh, advancing, bracketed telemetry and fresh sensor
data. It rejects an invalid rigid transform and one differing from the
calibrated telemetry-derived sensor pose by over 0.3 m or 15 degrees. Sensor
health reports `pose_source: cpu_capture`. Diagnostics include
`world_from_sensor_used` and `pose_source` as well as the telemetry and
calibration matrices.

`Content/Python/mars_cpu_lidar_setup.py` provides an editor-only temporary
setup. It re-resolves the actor and component after every property change,
because Blueprint post-edit reconstruction can replace the object a Python
variable refers to. It verifies all settings and tries to restore the previous
values if an edit fails. It sets 160 columns, 120 channels and 5 Hz for a
bounded initial experiment. It does not save the level or verify PIE settings.
The returned `restore_source` identifies whether `restore_values` were supplied
by the caller or captured just before applying this setup. After stopping Play,
call `restore()` in the same editor session to restore those stored values.

No obstacle is removed or classified as ground by this feature. Positive and
negative height residuals, the obstacle threshold, vehicle footprint and
sensor freshness checks are unchanged. CPU line traces see collision geometry,
which may differ from GPU-rendered geometry. Invalid returns and insufficient
coverage do not establish free space. Reduced scan resolution can miss small
hazards; this experiment is not evidence that a route is safe.

The C++ reflection layout changes: fully close the editor and do a normal
Unreal build, rather than relying on Live Coding. CPU scans can be expensive;
measure frame rate, freshness and actual coverage on the target machine.
The simulator must be validated natively before relying on this mode. A good
first check is an idle snapshot, followed by a short, supervised controlled
motion test with a fresh mission recording and verified positive and negative
hazard cases. Do not alter tick groups or component properties during Play.

For the first moving check, start `tools/record_mars_mission.py --seconds 180
--fusion-shadow` and wait for `KAYIT_HAZIR`. In another terminal,
`tools/mars_cpu_lidar_short_probe.py` validates the CPU pose source, stationary
rover, sensor freshness and the inflated map before sending one goal 2 m away
at a 25-degree heading offset. It stops on a detected replan, stale pose,
persistent sensor wait, sampled distance limit, or timeout, and requests stop
after any goal attempt. The recorder is read-only. A sampled distance limit and
synchronous HTTP timeouts are not hard real-time guarantees; supervise Unreal
and keep its Stop control available. A successful run does not validate small
obstacle coverage or prove future routes safe.

## Known-obstacle detour check

`tools/mars_detour_probe.py --goal X Y` reuses the same preflight but plans to
an operator-chosen local goal on the service's live inflated `/map` with this
checkout's planner, and prints `MARS_ROTA_ONIZLEME` without sending anything.
It fails closed if the service manifest hash, grid size or static terrain
blocks differ from the local bundle. `test_type` is
`pre_existing_obstacle_detour` only when the straight segment is closed on the
inflated live map; that is a planner label, not verification of the obstacle.

Repeat with `--send --expect-session <id> --expect-map-revision <n>` copied
from a fresh preview. The goal is sent only if the repeated preflight sees the
same session and map revision. Motion stops on any replan, session/mission
change, stale pose, lost CPU LiDAR, route-derived time/distance bounds, or a
sampled cross-track error above 0.75 m from the previewed route; stop is
requested after any goal attempt. `MARS_ENGEL_DOLASMA` reports the stop reason,
maximum sampled cross-track error and map revisions seen. A pass is evidence of
following a route around an obstacle already in the map; detecting an obstacle
introduced during motion and the subsequent replan is a separate test, which
this probe deliberately stops on. A 2026-11-23 offline reconstruction of the
2026-11-05 cube record (bundled DEM plus its three recorded LiDAR cells,
start/goal from the later preview) reproduced the earlier 12.131 m route; that
is not a native drive.

`--allow-replan` keeps driving through service replans caused by newly
observed cells; cross-track is then measured against the service's active
plan and the summary lists plan and map revisions. Brief
`waiting_for_fresh_data` states (a control decision whose inputs expired, sent
as a zero command) share the existing 3 s continuous sensor-wait bound instead
of ending the probe at once.

Native run, 2026-11-24, level `JezeroRover_5c8b3fa632eb`, temporary unsaved
1 m cube at UE (-12590, 11830, 570) cm, CPU LiDAR 160x120 at 5 Hz with capture
pose, session `f8125483-1985-4386-94ae-3134553d78c7`:

- Without `--allow-replan` the probe stopped after 3.4 s: ground-truth depth
  first saw the cube's second row (cell [118,126], residual 0.55 m) and the
  service replanned correctly.
- With `--allow-replan`, mission `07e1823a…` drove 1.3 m and stopped on the old
  immediate `waiting_for_fresh_data` rule; mission `791b82c8…` then continued
  from (127.0, 124.85) and `arrived` after 87 s: 10.90 m XY, final error
  0.248 m, maximum sampled cross-track 0.16 m, no replan, closest rover centre
  1.60 m from the cube footprint. Records:
  `Saved/Mars/gorev-izleme-*-239bd88a4a334395a67a88b26d2f7304.json`.
- An earlier session (`b504fcfb…`, mission `93f1bedc…`) stopped when
  ground-truth depth added six ground-level cells in a band near 8 m
  (residual 0.150-0.159 m) during the initial turn-in-place, with frame body
  pitch -5.6 deg. Bridge telemetry during turns showed pitch from -6 to +7 deg
  and up to 2.1 deg change between consecutive 33 ms samples, so a one-sample
  capture/pose offset explains this magnitude at 8 m. This is a measured
  hypothesis, not a proven cause; it is unresolved.

This shows following a planned route around one known, already mapped
positive obstacle in simulation. It is not validation of small rocks, negative
hazards, depth false positives, or obstacles introduced during motion.
