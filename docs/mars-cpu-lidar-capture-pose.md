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
