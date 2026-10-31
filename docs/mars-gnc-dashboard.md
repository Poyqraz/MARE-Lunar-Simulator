# Mars GNC dashboard prototype

This prototype adapts the original MARE GNC mission-control interface from
upstream commit `e86ee76c1cc5d14818b893c5f5efd299dd380e9d` to the existing
ROS-free Python navigation service. Upstream and three.js licenses are retained
in `mars_rover/dashboard_assets`. The original minimal interface remains at `/`;
the adapted interface is served locally at `/dashboard` on port 8766. Docker
and ROS are not required by the adapter.

The orbital background is a static HiRISE reference, not a live satellite feed.
The terrain map is the existing DEM; positions and route come from simulation
telemetry and the active planner. The LiDAR display is downsampled for display
only. Its height colours use a scan-based estimate of ground, and its range
is relative to the rover-body origin; neither is a calibrated terrain analysis.
The displayed pose update rate is the browser's rate, not raw telemetry rate.
The local 3D view is sampled ground-truth depth, not an independently
validated hazard classification. Missing or expired data is not free space.
Camera JPEG previews are subsampled to a maximum of 320 by 240 pixels (for
example, 640 by 480 becomes 320 by 240); full-resolution sensor frames remain
available to navigation. Sampling can hide small features in the preview.
The central RGB camera ID defaults to 0 when absent from the exported sensor
configuration; verify it in Unreal before trusting the camera and projected
path alignment. The projected 0.65 m route width is a reference assumption,
not a measurement of the user's vehicle.

Unreal viewport switching requires an independently running editor-side
`rover_cameras` link and a compatible rover/camera setup. It changes the
Unreal viewport, not a live video embedded in the dashboard. Recording,
snapshots, lights, node restart and the original obstacle-avoidance switch are
disabled until implemented against this backend. The interface and motor
behavior with it open still require native UE 5.7.4 and browser acceptance;
Python unit tests alone do not establish visual alignment or performance.

An initial native dashboard-open drive on UE 5.7.4 reached neither its goal nor
the 0.25 m arrival threshold before the 30 s test stop. The history recorded
stale captures, observer pose gaps, and multiple replans. A near-goal replan
sent the rover toward the centre of its current grid cell, behind its actual
position; the planner now bypasses that centre only when the direct connection
to the next waypoint passes the existing collision checks. The reduced preview
encoding is a resource mitigation, not proof that the observed lag is fixed.
Native repeat testing and a dashboard-closed comparison are required.

The camera route overlay is requested only for an active plan; an unavailable
plan or missing capture is still a normal 404. If an HTTP client disconnects
while a response is being written, that response is abandoned without changing
the vehicle mission. The dashboard reports a terminal mission's saved error
when available, and otherwise shows the original blocked/timeout state.

For a native mission observation, `python tools/record_mars_mission.py --seconds 150`
polls the local mission status and periodically writes two unique, atomic JSON
checkpoints under `Saved/Mars`. It stops monitoring when a new/current active
mission closes, or after the time limit. It only reads the mission snapshot and
export endpoints: it never sends a goal or a stop command, including on timeout.
If the service becomes unavailable, the files retain the last successful
checkpoint; events after that checkpoint cannot be recovered from those files.

For a short native diagnosis, add `--obstacle-diagnostics` when starting the
navigation service. The mission export then includes a bounded history of the
sensor frames that marked new raw obstacle cells: source, capture timestamp,
capture-time transform, map revision, counts and one sample per newly blocked
cell. A failed planning attempt also records whether its start and goal are
blocked and which raw cells contribute to footprint inflation. At most 128
changed frames and 256 cells per frame are retained; eviction or truncation is
reported. If a frame contains more cells, those nearest the capture-time rover
position or active goal are prioritized. Records include their session and mission ID because the map can
outlive a mission. These samples cannot establish whether an obstacle is real
or determine a calibration error on their own; missing samples do not mean
free space. This optional collection costs processing time, so assess native
control timing independently. It does not alter obstacle thresholds or permit
movement on blocked or stale data. It is stored in memory until exported; the
read-only recorder above checkpoints the export during a mission.

The same option exposes the most recent 16 decoded LiDAR deliveries as
`lidar_ingest_timing` in `/status`, `/mission/snapshot`, and `/mission/export`.
Each sample compares the scan timestamp with the most recently received rover
telemetry immediately before and after `feed_lidar`, reports the telemetry's
wall-clock arrival age and connection state, and measures the feed call's
elapsed wall time (including any session-lock wait). The pre-feed lag can
already contain GPU, sender, TCP, socket-buffer or decoder delay; these data
cannot split those stages. A stale or missing telemetry reference cannot prove
capture latency. Timing samples and obstacle records are diagnostic only and
never extend the source data deadlines.

Depth back-projection and range filtering run outside the navigation session
lock, using the complete in-range frame and retaining the original receive
timestamp. Capture-pose application and obstacle-map mutation remain under the
session lock. The sensor health report splits preparation and locked processing
times; native performance and sensor freshness must still be checked.

In a later native turn, mission history recorded repeated ground-truth depth
capture waits at 0.433–0.467 s. The previous UnrealStereoCam pump only polled
GPU readbacks when another capture was due, introducing a polling interval of
up to one `SendHz` period. The component now polls on each game tick while
starting captures and readbacks only at the configured rate. Capture timestamps
remain those of the original capture, and freshness limits are unchanged. An
isolated C++ tick simulation checks scheduling, but UE compilation, GPU
readback behavior and runtime performance require native verification. At
BeginPlay the updated binary logs `UnrealStereoCam: per-tick readback polling
enabled`; its absence means the new plugin cannot be assumed to be loaded.

The same turn ended blocked because LiDAR samples marked the goal cell and
neighbours; the recorded sample heights were below the DEM. These observations
do not establish whether the surface has a real discrepancy or whether sensor
projection/capture timing is responsible. The obstacle classifier remains
conservative until that discrepancy is measured against the actual Unreal scene.
With the same rover level open, the Unreal Editor Python console can run
`import mars_lidar_collision_probe as p; p.probe_goal(r"C:/path/to/mission-export.json")`.
It performs read-only simple and complex vertical collision traces at recorded
goal-contributor sample coordinates and prints `MARS_LIDAR_COLLISION`. It uses
the sole active PIE world when available, otherwise the editor world, and
reports the selected world and hit actors. A vertical collision probe measures
the current world, not the historical moving LiDAR capture or the renderer's
depth, so matching collision and DEM alone does not establish the sensor error.

In a subsequent editor-world probe of level `JezeroRover_d18c24b80675`, both
collision modes hit `Landscape_0` at the three saved sample coordinates. The
collision heights differed from the DEM by at most 2.6 mm and were 20.3–22.6 cm
above the recorded LiDAR points. The saved export does not identify its Unreal
level, so the editor probe alone does not prove it was the same historical
world. The scene's sensor IDs and editor-time body-relative depth and LiDAR
matrices matched the selected configuration. A Live Coding build succeeded and
the per-tick StereoCam marker appeared at BeginPlay; eight idle snapshots had
positive LiDAR/depth point counts and no reported processing error. Those
observations do not establish timing under motion or the cause of the LiDAR
height discrepancy.

`mars_lidar_live_probe.probe_idle(path_to_sensor_config)` is a bounded,
read-only comparison for one idle PIE world. It fetches the already downsampled
and rounded dashboard LiDAR points using HTTP GET, maps them with the current
PIE `base_link` transform, and traces up to 48 corresponding vertical rays. It
reports trace actor classes, signed height differences by range, a current-body
versus latest telemetry comparison, and the current sensor-to-body calibration
difference. It accepts `idle` or `new_session_requires_goal` with no active
mission, plus fresh telemetry, near-zero reported speed and
angular components, zero wheel commands, and an at-most-0.4 s scan/pose gap.
Those checks are a screen, not proof that the rover was stationary for the
entire capture interval. Current collision and current pose do not reconstruct
the old moving scan or necessarily match the GPU-rendered surface; this probe
does not classify obstacles or change navigation.

One native idle PIE run on `JezeroRover_5c8b3fa632eb` compared 48 dashboard
LiDAR points at 3–8 m with complex collision. All hit `Landscape_0`; none of
the sampled vertical differences was greater than 9 mm in magnitude or below
-0.15 m. The current scene body's pose differed from the latest telemetry pose
by about 0.000017 m and 0.0017 degrees; the live sensor-to-body matrix matched
the configuration to floating-point precision. The scan timestamp was 0.10 s
behind that telemetry. These are rounded/downsampled display points at a
stationary pose, at a different location and in a differently named level from
the earlier editor collision probe. They do not establish alignment during a
turn or identify the Unreal level of the earlier blocked mission.

The earlier blocked run contained both above- and below-DEM obstacle samples in
different moving LiDAR frames. The LiDAR component is configured to tick
post-physics in source, while the rover Blueprint's actual telemetry production
phase has not been measured. Tick order and capture-time body pose are possible
contributors, not established causes; tick-group settings state minimum tick
groups and do not prove when a Blueprint emits telemetry or when rendering
captures it.

The next runtime inspection on the same PIE level reported the rover actor's
primary tick as enabled, `TG_PrePhysics`, and its LiDAR component's minimum
tick group as `TG_PostPhysics`. This strengthens the possibility of a
physics-phase mismatch, but does not show where the Blueprint emits telemetry
or prove the GPU render uses either measured pose.

An opt-in diagnostic logs the `base_link` transform on the game thread just
after each GPU LiDAR capture request when the PIE rover has the transient
`MarsLidarPoseProbe` tag. Normal scans do not log; it does not change tick
groups, commands, packets, or obstacle thresholds. With Play running,
`mars_lidar_pose_diagnostics.enable()` adds the tag to that PIE actor and
`disable()` removes it. Stopping Play discards the transient actor. Logging can
affect performance, so enable it only for a short controlled observation.
It records the scan's double-precision simulation timestamp converted to ns,
which can differ slightly from integer-ns telemetry. The offline command
`python tools/analyze_mars_lidar_pose.py Saved/Logs/Moon_Simulator.log`
reads a bounded log tail and compares uniquely matching rover Blueprint
telemetry and request-pose timestamps within 1024 ns. It rejects ambiguous
matches and reports pose differences and an illustrative 8 m body-forward
height difference. The parser currently accepts the observed tr-TR Blueprint
log format only. It does not measure the actual GPU-render pose or prove the
cause of an obstacle. Native UE compilation and a controlled turn are required
before drawing any conclusion.

`python tools/mars_lidar_turn_probe.py` is an optional **motion command** for
this simulator, not the read-only diagnostic above. It requires current,
advancing matched pose-log lines, a fresh idle rover with zero wheel commands,
low linear/angular velocity, fresh LiDAR and ground-truth depth, the expected
tr-TR telemetry format, and a clear inflated-map segment. It selects a temporary
goal 2 m behind the rover and requests a stop when it observes about 45 degrees
of rotation, 0.2 m of net displacement or sampled path length, a terminal
state, or an 8 s target duration. Sampled movement cannot guarantee the full
path length between samples.
Synchronous HTTP calls or a failed stop can overrun those targets: an operator
must supervise and can stop PIE. The tool attempts `/stop` even when the goal
request times out, prints a failure if the stop is not acknowledged, and saves
the observations and available mission export under a unique `Saved/Mars` name.
If the goal response is missing, the user must stop PIE even when `/stop` was
acknowledged: separate HTTP requests may be processed out of order. It also
attempts a stop as soon as a polled pose becomes stale or its clock stops.
The resulting pose comparison remains request-time versus telemetry, not a
measurement of GPU render-time pose or a safety qualification.

On the native controlled turn in PIE `JezeroRover_5c8b3fa632eb`, the logger
matched 50 of 50 request-pose records to Blueprint telemetry in the reported
window, which includes pre-turn and post-stop frames. The p95 and maximum
up-axis differences were 2.588 and 3.200 degrees; request and telemetry poses
are compared with the same simulation stamp. The 8 m body-forward point had
illustrative absolute p95/max vertical differences of 0.372/0.416 m. These are
not measured errors of actual terrain returns or GPU render poses.

While mission `6b7d419f-5e0b-4c1a-a2aa-cc2602b075d2` was active, five LiDAR
diagnostic frames introduced 43 previously unblocked cells and four depth
frames introduced 19. Two LiDAR map-change frames and two depth map-change
frames shared a frame number with a large logged LiDAR request/telemetry pose
difference. Another 16 cells were recorded after the mission ended. This
coincidence raises a concrete hypothesis but does not prove the cells are clear,
that depth and LiDAR used identical render poses, or that the earlier aborted
mission had the same cause. The test stopped deliberately after a turn, not
because its goal was reached. One `waiting_for_sensors` event reported LiDAR
capture age of 0.433 s. Large rejected-line counts in the older summary cover
the scanned log tail; they are not counts of unmatched frames in this turn.
The observed last turn sample was approximately 56 degrees, beyond the 45
degree target. The observer recorded a 0.265 m XY path even though its net
displacement remained below 0.2 m. The turn tool now sums sampled movement as
well as checking displacement, but both may exceed their targets between
polls and neither represents a real-time stop guarantee.

`tools/analyze_lidar_pose_residuals.py` reads that test's JSON and Unreal log,
matches LiDAR map-changing frames by both frame ID and capture stamp, verifies
the terrain manifest and recorded sample residuals, then reprojects the one
recorded representative point per cell with the logged request-time body pose.
It does not contact the service or modify the log, source report, or map. Its
counterfactual is useful for sizing the effect, but it does not prove GPU
render-pose identity or a rigid sensor mount during motion, replay all points,
or authorize clearing a cell. Unique
request matches are required; missing and ambiguous matches are reported.

The native request-pose replay matched all five mission LiDAR frames and 43
representative samples. All 43 reprojected samples were within the 0.15 m
height threshold under the logged request-pose assumption. This is strong
evidence that the observed pose difference can account for these selected
samples, not proof of a clear cell or actual GPU render-time pose. It does
not cover the depth map's 19 new cells or every return in any cell.

`mars_tick_alignment_probe.apply()` is an opt-in experiment on live PIE
objects. It checks for an idle, fresh, stationary rover with zero wheel
commands, then sets the actor's minimum tick group to `TG_PostPhysics` and
the LiDAR and navigation-camera components to `TG_PostUpdateWork`. It logs
before/after groups and attempts rollback on failure; stopping Play discards
the runtime changes. It does not send a goal or alter assets. The Blueprint
telemetry phase and camera/LiDAR render poses remain unverified, and shifting
the actor tick may change control latency. A supervised, recorded A/B test is
required; this is not a permanent fix or a change to obstacle thresholds.

The current service keeps dynamic occupancy across PIE reconnects. To compare
with a fresh map, export any needed mission history first, stop Play, and
restart the navigation service with `--obstacle-diagnostics` before Play.
Stopping the service discards its in-memory map and history; the export does
not restore that map. Do not infer that previously marked cells were all false.

One aligned test attempt failed the LiDAR preflight before sending a goal.
Subsequent stationary samples were taken in navigation session `e3e79056`,
whereas the last recorded tick-alignment call was in `f57b3886`. A new
navigation session can arise from several causes and does not by itself prove
that Play restarted; the current PIE tick groups and diagnostic tag must be
rechecked. In each of the five samples labelled logging on and five labelled
logging off, reported LiDAR arrival age was 0.031–0.172 s, pose-to-processed
LiDAR capture difference was 0.067–0.167 s, and the valid count was at least
52,987. None reproduced the original preflight rejection; depth capture age
was not recorded. The labels alone do not establish the tag's state in the
new session. The second telemetry timing snapshot's lifetime maximum parsed
interval was 1.234 s while the reported maximum capture gap was 0.0334 s;
the reason and exact timing are not established.

The turn probe now reports which LiDAR/depth preflight condition failed and
the relevant values. Its thresholds and the prohibition on sending a goal
when preflight fails are unchanged.

A subsequent native tick-alignment call reported session `13470f98` with the
actor in `TG_PostPhysics` and LiDAR/camera components in `TG_PostUpdateWork`.
The following turn probe rejected its idle/pose/clock preflight before sending
a goal. The old error did not identify which of these three checks failed or
which preflight sample was involved; the session at the failed check is also
unknown. No aligned turning measurement resulted from that attempt.

The probe now includes the failed preflight sample number and reports the
actual state, pose-fresh and clock-advancing flags, pose age, observer error,
and session ID. These are copied from the snapshot that failed, not a later
observation. Neither acceptance checks nor navigation thresholds are changed.
`tools/check_mars_readiness.py --expected-session <id>` samples the mission
snapshot and bridge status three times via local GET requests only and checks
the current preflight fields without sending a goal or stop. These later
samples cannot reconstruct the already-failed preflight, and each bridge
status is a separate request from its adjacent mission snapshot.
