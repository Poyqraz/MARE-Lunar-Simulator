# Mars review and validation — 2026-10-28

The reviewed increment targets a correct Jezero environment plus geometric
navigation with the existing sensor protocols, before user CAD integration.
The earlier local 32-test increment was reviewed and
extended; it is not treated as proof of Unreal runtime behavior. A second
scientific-fidelity review adds dense source checks and native collision gates;
see mars-scientific-review.md and data/jezero-fidelity.json.

## TDD findings

New tests first exposed these failures, then passed after corrections:

- An Earth projected-metre raster could be accepted as Mars.
- Non-finite geotransforms did not get a clear early validation failure.
- Changing a manifest Z scale/offset could pass file-hash checks.
- The scene required a rover even for environment-only work.
- A world switch could leave a stale deferred save; concurrent builds were allowed.
- Required editor Python/landscape plugins were not explicit in the project descriptor.

Further tests cover local reference-body geodesic distance, bilinear height
orientation, incomplete ortho coverage, false-colour rejection, source texture
orientation, solar azimuth axes, Earth ozone removal, unlit reference lighting,
the requirement for a real editor readback report instead of exit-code-only success,
UE texture UV pin-name resolution, explicit region naming for custom sources,
and absolute report paths when launching from a relative project folder.

## Terminal checks

```text
python -m pytest tests -q
122 passed
python -m ruff check mars_rover tests Content/Python/mars_*.py tools/unreal_mars_smoke.py tools/mars_fidelity_figure.py tools/mars_navigation_benchmark.py
All checks passed!
```

Compilation/import checks, CLI help paths and git diff whitespace checks are
also run. CI repeats Python tests and lint on Windows/Linux with pinned Python
3.12 dependencies; consult the PR checks for its actual remote status.

The first actual Windows CI run found a CSV hash mismatch caused by Git's
CRLF conversion. A new test reproduced it with `core.autocrlf=true` before
the fix. Hashed CSV/manifest files now have explicit LF checkout attributes,
binary heights remain binary, and the generator writes LF on every platform.
The source-data hashes were retained; validation was not weakened to hide the issue.

## Measured data experiment

The official USGS DTM and its matching 25 cm grayscale orthoimage were read.
The source region was transformed to a 252 x 252 m local Mars reference-body
scene, with a separate registered 1024 x 1024 display image. Independent
inverse-coordinate transforms and four-source-post interpolation checked five
terrain control points; their expected heights are frozen in the regression test.
Three independently sampled image points check the displayed reference texture.
The second review compares ALL 64,009 terrain posts with an inverse-coordinate,
independent four-post bilinear source calculation. It passes a 2e-6 m numerical
tolerance; this is conversion fidelity, never ground-truth accuracy. The full
original source fingerprint and unmodified metadata XMLs are now verified too.

The source grid's east-west ground/grid factor at the selected latitude is
0.9487174175. Current converted heights range approximately
-2580.582017 to -2572.593266 m, with about 0.000122 m r16 quantization. These
values describe conversion, not DEM accuracy. Maximum finite-difference slope
is about 15.84 degrees on a 2 m central-difference baseline (95th percentile
5.10 degrees with the boundary excluded). The candidate-triangle upper bound
is about 21.12 degrees. A 15-degree GNC threshold does not certify traversability.
The review image shows line-like slope features requiring source-quality
inspection; no smoothing is applied to disguise possible stereo/editing artifacts.

The original orbital PNG was visually inspected as data, not presented as an
Unreal render. The included image is grayscale, contains baked shadows and
has controlled display contrast. It is not a radiometric true-colour/albedo product.

## Explicitly pending

No Unreal Editor executable/GPU runtime is present in this environment.
Therefore these have NOT been executed here:

1. Native UE 5.7 plugin compilation and actual Landscape/material import.
2. GPU/Substrate shader appearance, atmosphere/exposure and viewport inspection.
3. Dedicated `python -m mars_rover.unreal_check --editor ...` acceptance on Windows.
4. The new native collision acceptance: 260 points, 520 simple/complex traces,
   full-resolution mip 0, terrain actor identity and 2 mm numerical tolerance.
5. Native rover stability/calibration, sensor mount/stream geometry and
   click-to-goal driving tests. Their Python contracts have tests; the engine
   behavior itself remains pending.

The terminal launcher and editor-state contracts have unit tests; those are
not a substitute for running the actual engine. Generated reports retain
`gpu_render_verified=false` and `visual_qa_passed=false` until separately
validated. The interactive/terminal acceptance procedure is in the Mars guide.

References and scientific limits are documented in mars-research.md. No
soil sinkage, dust dynamics, thermal response, true sensor localization or
user-specific CAD/controller behavior is claimed by passing Python tests.

## ROS-free navigation review

The 35 repositories in the public Mars star list plus nine related stars were
inventoried; selected core source was read. See
[the per-repository decisions](mars-starred-review.md) and
[the implementation/acceptance plan](mars-navigation.md). External projects
were not executed and none of their source/assets were vendored.

TDD first failed for the missing planner/sensor/navigation modules, malformed
organized LiDAR indices, missing explicit runtime plugins, and changed camera
resolution/invalid stereo calibration, and sparse old poses incorrectly
satisfying the settling window. Corrections passed the full suite.
Coverage includes synthetic crater/pit avoidance, NaN/no-return handling,
footprint clearance, diagonal corner cuts, exact blocked/out-of-map goals,
real bundle loading, capture-time full attitude, pose bracketing, all five
shared clocks, new-Play reset, settling, stale/absent sensors, stop-before-replan,
and manual override through the legacy motor API.

Two tests use real localhost TCP/HTTP sockets: LIDR/NAVF input reaches the motor
command socket and loss of the camera connection causes zero wheel commands;
the mission map and old `/stop` API connect to the navigation session. These
are protocol/control tests with synthetic sensor/telemetry fixtures, not UE.
The actual OpenCV SGBM recovers a known 8-pixel shifted textured plane at 2.4 m
and rejects unsynchronized/unrectified pairs. It is not a real sensor benchmark.

`tools/mars_navigation_benchmark.py` reproduces the frozen
[four-route report](data/navigation-validation.json). All four routes stay
inside the inflated traversable map; a no-slip planar tracker reaches within
0.25 m and stops. The measured path lengths are about 76.8–84.8 m. The model
uses exact pose and has no wheel contact, stereo, LiDAR, slip or native physics.
CI runs this benchmark independently on both platforms. The route plot was
visually inspected as a data plot; it is not an Unreal screenshot.

The new editor helper exports actual placed sensor geometry before Play.
Missing timestamps or changed intrinsics are rejected rather than silently
substituted. A map/goal UI is wired to the Python service. Native flags remain
false in exported config and offline reports. Partial missing/occluded returns
do not certify a fully observed driving corridor, and the planner still relies
on the known DEM prior. No claim of complete negative-obstacle detection or
wheel-scale fidelity is made.

## Reviewed mission-history increment (A1)

The dual-view plan was rechecked against its recorded PR head. Its dependency
order, memory versus durable storage, coordinate-frame naming and sampled
distance semantics were clarified in [the follow-up review](mars-dual-view-review.md).
The follow-up branch implements continuous observation and bounded mission
history, not the native camera extension.

Ten additional tests cover idle/terminal observation, frozen finished records,
original-plan retention across replanning, Play/clock reset, pose gaps/teleports,
paused/stale speed, canceled queued goals without invented endpoints, bounded
archives/cursors, detached exports and real HTTP read-only/slow-reply behavior.
The initial missing-feature and lock failures were observed before implementation;
three further archive/cursor defects were reproduced and corrected. The complete
suite now passes 122 tests. The four-route benchmark and Ruff checks also pass.
No native Unreal camera, GPU, packaged-app or click-to-goal acceptance is claimed.

New TDD coverage first failed for absent full-grid fidelity/collision tools,
unvalidated dust scenario parameters, source XML byte preservation, and the
new XML Windows checkout case. Tests now reject missing/wrong/shifted collision,
exit-code-only reports, invalid optical-depth/SSA/scale parameters, changed
metadata, and a shifted source origin. The dust column integral is checked
analytically. Fake-engine results do not constitute native execution.
