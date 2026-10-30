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
