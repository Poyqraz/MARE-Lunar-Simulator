# Mars review and validation — 2026-10-28

The reviewed increment targets a correct Jezero environment before user CAD
or autonomy integration. The earlier local 32-test increment was reviewed and
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
80 passed
python -m ruff check mars_rover tests Content/Python/mars_*.py tools/unreal_mars_smoke.py tools/mars_fidelity_figure.py
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
5. Rover stability/calibration, sensor/TF geometry and click-to-goal tests.

The terminal launcher and editor-state contracts have unit tests; those are
not a substitute for running the actual engine. Generated reports retain
`gpu_render_verified=false` and `visual_qa_passed=false` until separately
validated. The interactive/terminal acceptance procedure is in the Mars guide.

References and scientific limits are documented in mars-research.md. No
soil sinkage, dust dynamics, thermal response, true sensor localization or
user-specific CAD/controller behavior is claimed by passing Python tests.

New TDD coverage first failed for absent full-grid fidelity/collision tools,
unvalidated dust scenario parameters, source XML byte preservation, and the
new XML Windows checkout case. Tests now reject missing/wrong/shifted collision,
exit-code-only reports, invalid optical-depth/SSA/scale parameters, changed
metadata, and a shifted source origin. The dust column integral is checked
analytically. Fake-engine results do not constitute native execution.
