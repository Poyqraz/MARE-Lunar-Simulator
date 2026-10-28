# Measured Jezero starter terrain and orbital reference

The measured source is **High-Resolution Imaging Science Experiment Digital
Terrain Model Jezero_C; ESP_045994_1985, ESP_046060_1985aa**, USGS, published
2020-07-24. The paired grayscale orthoimage is ESP_045994_1985 at 0.25 m
source grid spacing. This is not a procedural Mars lookalike or true-colour image.

- [Catalog](https://astrogeology.usgs.gov/search/map/mars-2020-jezero-crater-landing-site-products)
- [DTM GeoTIFF](https://asc-pds-services.s3.us-west-2.amazonaws.com/mosaic/mars2020_trn/HiRISE/DTM_MOLAtopography_DeltaGeoid_Jezero_C_Edited_affine_1m_Eqc_latTs0_lon0.tif)
- [DTM metadata](https://asc-pds-services.s3.us-west-2.amazonaws.com/mosaic/mars2020_trn/HiRISE/DTM_MOLAtopography_DeltaGeoid_Jezero_C_Edited_affine_1m_Eqc_latTs0_lon0.xml)
- [Orthoimage](https://asc-pds-services.s3.us-west-2.amazonaws.com/mosaic/mars2020_trn/HiRISE/ESP_045994_1985_Edited_affine_25cm_Eqc_latTs0_lon0.tif)
- [Orthoimage metadata](https://asc-pds-services.s3.us-west-2.amazonaws.com/mosaic/mars2020_trn/HiRISE/ESP_045994_1985_Edited_affine_25cm_Eqc_latTs0_lon0.xml)

DTM originators: Robin Fergason, Donna Galuszka, Trent Hare, David Mayer,
Bonnie Redding and Ethan Smith. Credit USGS Astrogeology and the
NASA/JPL/University of Arizona HiRISE team. Source terms remain applicable;
these derived data are not relicensed as original MIT software. The DTM
metadata lists access/use constraints as None.

Read on 2026-10-28. Full original DTM SHA-256:
`0c681fa0c2fa72ec2253d09ed8643d5794ea0c3575f5fa953d470cc0beeb1751`.
The original large files are not committed.

The selected source window is column 3278, row 6970, width/height 505. It is
reprojected to a Mars azimuthal-equidistant grid centred near 77.4421842 E,
18.4287659 N. Its 253 vertices per axis at 1 m spacing span 252 x 252 m on the
reference-body grid. The source's lat_ts=0 equirectangular grid has an
approximately 0.9487174 east-west ground/grid factor here; source grid metres
are not passed unchanged to scene metres.

Heights use point-sampled bilinear interpolation with exact coordinate
transformation (tolerance=0, XSCALE=YSCALE=1). Rows are reversed to local north;
the minimum is subtracted for local z, and r16 quantization is recorded. The
PNG is separately reprojected to the same extent, north-up, with standard
bilinear footprint resampling. It is contrast-stretched grayscale (1st/99th
percentiles); it is not albedo or recovered surface colour. Its baked orbital
shadows are displayed with an unlit material, not relit with a second Sun.

The heightmap's horizontal mirror and actor offset implement MARE's
`UE.x=-ROS.x`. CSV rows increase north, PNG rows increase south; UV mapping
is explicitly `u=x/extent_x`, `v=1-y/extent_y`. The manifest records source/target
CRS, source windows, datum offset, reference radius, processing and hashes.
Zero and negative heights remain valid. NoData is rejected rather than filled.

`elevation.csv` is space-delimited for GNC. `soil.csv` is only a boundary
no-go mask, not measured geology, traction, sand depth or bearing strength.
Scene colour/noise and atmospheric scattering coefficients are illustrative;
no fabricated microtopography or collision rocks are added. DTM sampling
interval is not scientific accuracy; small features and stereo artifacts remain.

Reproduce into a NEW output folder with Python 3.12 outside Unreal:

```bash
python -m pip install -r requirements-mars.txt
python -m mars_rover.prepare --output generated/jezero
```

The [preset](../../../Config/Mars/jezero.json) captures the input selection.
Network is needed to regenerate; the included bundle can be used offline.
