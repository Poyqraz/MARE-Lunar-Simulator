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
difference. It requires idle/fresh telemetry, near-zero reported speed and
angular components, zero wheel commands, and an at-most-0.4 s scan/pose gap.
Those checks are a screen, not proof that the rover was stationary for the
entire capture interval. Current collision and current pose do not reconstruct
the old moving scan or necessarily match the GPU-rendered surface; this probe
does not classify obstacles or change navigation.
