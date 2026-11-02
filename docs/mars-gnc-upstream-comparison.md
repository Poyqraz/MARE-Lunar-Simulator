# Upstream GNC and Mars adapter: code-level comparison

This review covers `raulcastar/GNC-Moon-Simulator` commit
`e86ee76c1cc5d14818b893c5f5efd299dd380e9d`, its planner, local mapping,
rover controller, perception, mission-control, and testing documentation.
It is a targeted review, not a claim that every Unreal asset or every upstream
test was executed on the Mars scene.

The upstream suite has separate Unreal, ROS 2 GNC and Terrain Studio projects.
The published GNC uses a fast-marching global planner, a DWA local controller,
LiDAR detection, a stereo-derived local DEM, ROS topics and a web dashboard.
The Mars adapter reuses the overview interface but drives a distinct ROS-free
Python backend; visual similarity does not make its algorithms equivalent.

## LiDAR and mapping

Upstream [`lidar_obstacles.py`](https://github.com/raulcastar/GNC-Moon-Simulator/blob/e86ee76c1cc5d14818b893c5f5efd299dd380e9d/component_path_planner/src/lidar_obstacles.py)
levels the scan using the configured mount pitch, fits a near-field ground
plane, keeps returns above a height threshold and thins the result. Its
`ObstacleMemory` prunes local obstacle points by age and distance. In
[`component_path_planner.py`](https://github.com/raulcastar/GNC-Moon-Simulator/blob/e86ee76c1cc5d14818b893c5f5efd299dd380e9d/component_path_planner/src/component_path_planner.py),
however, global `_obstacle_cells` are unioned into a set and cleared on an
odometry session jump; the 20-second local memory is not a 20-second expiry
for those global cells. The LiDAR callback transforms detections using the
latest stored pose, rather than an interpolated capture-time pose.

The separate upstream local-mapping node constructs a local elevation map
from stereo depth and odometry. The inspected path planner subscribes to odom,
goal, cancel and LiDAR; it does not subscribe to that local DEM as an input.
Do not describe this arrangement as a validated probabilistic fusion of every
sensor. Its ground-plane detector handles positive obstacles, not a complete
negative-obstacle or occlusion model.

The Mars planner compares each valid projected point to the static DEM and
permanently marks a raw cell if any positive or negative residual exceeds the
configured threshold. LiDAR and the selected depth source can both add cells;
raw cells are inflated for the footprint. This preserves potential hazards but
can accumulate projection errors. A blank or stale measurement is not evidence
of free space. Do not silently relax thresholds, delete occupied cells, or
disable the sensor gate to make a route succeed.

`tools/analyze_mars_map_disconnect.py` reconstructs a recorded failure from
the matching terrain and complete map-change history. Counterfactual routes
are diagnostic evidence only; they do not classify obstacles or authorize
motion. The script rejects missing frames, truncated cells, inconsistent map
revisions, a mismatched terrain manifest, and a failure it cannot reproduce.
It assumes the current planner code and limits match those of the recording.
An optional `--image new-file.png` saves the reconstructed failure grid for
offline inspection and never overwrites an existing file. It does not start or
control Unreal. A successfully reconstructed map may show a counterfactual
route, but the image shows the recorded mask, not a cleared one.

## Control, tests, and licensing

Upstream DWA constrains velocity and yaw-rate changes in its dynamic window;
its rover node also ramps target commands. Its README and testing guide show
demonstrations, unit tests with stubs, and scripts for live Unreal scenarios.
These do not establish acceptance for a different Mars level, sensor rig,
computer or locale. The upstream rover documentation warns that a single
`cmd_vel` can persist until a zero command; preserve the Mars adapter's
independent command expiry and immediate stop on invalid/stale data.

The upstream [agent guidance](https://github.com/raulcastar/GNC-Moon-Simulator/blob/e86ee76c1cc5d14818b893c5f5efd299dd380e9d/AGENTS.md)
documents that changing rover component properties during Play caused broken
wheel constraints. The experimental Play-time tick-alignment
script changes component tick properties and conflicts with that warning; do
not apply it to an active rover. A replacement must be designed and validated
without mutating the active Play components.

The upstream repository is MIT with stated exceptions: its fast-marching and
planner-map files and their tests are derived from GPL-3.0 DyMu. Check the
source notices before redistributing copied components. The offline replay in
this repository calls the existing Mars planner and does not import or copy
those upstream planner files.

## Dashboard and sensor sources

The global map overlays the current planner's actual inflated blocked mask.
Terrain restrictions, the first sensor to add each raw occupied cell, and the
footprint margin have separate colours. "First" is provenance, not proof of a
real obstacle or exclusive detection by that sensor. Uncoloured cells are not
verified clear; missing overlays are explicitly unavailable. The planner map
persists through a rover reconnection and is rebuilt on service restart. The
display adds no obstacle-clearing rule and does not change route decisions.

`--fusion-shadow` adds an opt-in, display-only comparison of the active LiDAR
and selected depth source. At most 8192 evenly selected world points per source
are retained, transformed using each capture's bracketed pose. A request to
`/dashboard/fusion-shadow` compares their DEM residual categories in shared
25 cm XY bins, provided pose, arrival and capture times are fresh and the two
capture stamps differ by at most 0.25 s. The dashboard shows the number of
shared bins where LiDAR has a threshold-crossing residual while depth has only
near-DEM sampled returns. The near-DEM band is one third of the existing
obstacle threshold and is an exploratory display parameter, not a calibrated
sensor tolerance. Incomplete/expired captures are labelled unavailable.
The frozen pair can still be reported if a newer ordinary frame arrives during
the calculation, provided the original pair remains fresh. Reconnects, pose
discontinuities and sensor transport failures invalidate in-flight results;
the response identifies its two capture stamps and arrival ages.

The two sensors may see different locations or occluded surfaces in the same
bin. The sample is not a complete scan, GPU render-time poses are unverified,
and ground-truth depth is another Unreal simulation output. These counters do
not verify obstacle reality or free space. They never change the grid, sensor
gate, or motor commands, and diagnostic errors do not suppress sensor updates.
Sampling and dashboard requests consume resources; test latency on the target
machine before using this optional observer during motion.

`tools/record_mars_mission.py --fusion-shadow` polls this read-only comparison
alongside mission snapshots and checkpoints both to local files. Before
reporting ready, this opt-in mode requires an idle rover, a fresh advancing
pose, estimated speed at most 0.02 m/s, zero wheel commands, and both service
diagnostics flags. It never sends a goal or stop.
The final `MARS_FUSION_RUN` summary matches sensor capture timestamps with
recorded LiDAR map changes within the same session and mission. Its polling
is intermittent; a missing match is not evidence of agreement. Timestamp
equality does not prove the same individual scan if unrecorded duplicate
timestamps exist, and an overlapping bin need not be a changed cell or ray.

The Mars overview consumes central/left/right RGB, ground-truth depth and
LiDAR when fresh. Its local 3D depth view is labelled ground truth. A rear RGB
stream can optionally be wired with `--rear-camera-id` when its ID is verified
in the active Unreal scene; an absent stream remains `NO SIGNAL`. This option
does not create or enable a camera in Unreal. All cameras currently share one
listener: any camera connection closure conservatively clears camera health
and stops motion, including closure of an optional camera connection. Stereo-depth display, masks,
event and SPAD views and ROS-specific recording/system controls require
separate real producers and adapters; placeholders are not evidence of data.

The Mars bundle already uses a measured USGS Jezero HiRISE DTM at 1 m sample
spacing and a registered 0.25 m/pixel orthoimage. These support terrain at
their documented resolution, not ground-truth 3D geometry for every rock.
Rover-based PDS mesh/XYZ products need their own coverage, frame, alignment,
and uncertainty checks before adding them to the same site.
