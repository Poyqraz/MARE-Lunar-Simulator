# Mars review and validation — 2026-10-28

The reviewed increment targets a correct Jezero environment before user CAD
or autonomy integration. The earlier local 32-test increment was reviewed and
extended; it is not treated as proof of Unreal runtime behavior.

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
61 passed
python -m ruff check mars_rover tests Content/Python/mars_*.py tools/unreal_mars_smoke.py
All checks passed!
```

Compilation/import checks, CLI help paths and git diff whitespace checks are
also run. CI repeats Python tests and lint on Windows/Linux with pinned Python
3.12 dependencies; consult the PR checks for its actual remote status.

## Measured data experiment

The official USGS DTM and its matching 25 cm grayscale orthoimage were read.
The source region was transformed to a 252 x 252 m local Mars reference-body
scene, with a separate registered 1024 x 1024 display image. Independent
inverse-coordinate transforms and four-source-post interpolation checked five
terrain control points; their expected heights are frozen in the regression test.
Three independently sampled image points check the displayed reference texture.

The source grid's east-west ground/grid factor at the selected latitude is
0.9487174175. Current converted heights range approximately
-2580.582017 to -2572.593266 m, with about 0.000122 m r16 quantization. These
values describe conversion, not DEM accuracy. Maximum finite-difference slope
is about 15.84 degrees, 95th percentile 5.11 degrees: the default 15-degree GNC
threshold will legitimately mark some cells impassable.

The original orbital PNG was visually inspected as data, not presented as an
Unreal render. The included image is grayscale, contains baked shadows and
has controlled display contrast. It is not a radiometric true-colour/albedo product.

## Explicitly pending

No Unreal Editor executable/GPU runtime is present in this environment.
Therefore these have NOT been executed here:

1. Native UE 5.7 plugin compilation and actual Landscape/material import.
2. GPU/Substrate shader appearance, atmosphere/exposure and viewport inspection.
3. Dedicated `python -m mars_rover.unreal_check --editor ...` acceptance on Windows.
4. Rover stability/calibration, sensor/TF geometry, click-to-goal or collision tests.

The terminal launcher and editor-state contracts have unit tests; those are
not a substitute for running the actual engine. Generated reports retain
`gpu_render_verified=false` and `visual_qa_passed=false` until separately
validated. The interactive/terminal acceptance procedure is in the Mars guide.

References and scientific limits are documented in mars-research.md. No
soil sinkage, dust dynamics, thermal response, true sensor localization or
user-specific CAD/controller behavior is claimed by passing Python tests.
