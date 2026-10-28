# Mars environment research and review decisions

Reviewed 2026-10-28 against the primary sources below. The engineering target
is a traceable Jezero environment in UE 5.7. Photorealism, scientific
radiometry, terramechanics and sensor-derived autonomy are separate acceptance targets.

| Source | Evidence and resulting decision |
|---|---|
| [USGS Mars 2020 landing-site products](https://astrogeology.usgs.gov/search/map/mars-2020-jezero-crater-landing-site-products) | Use a controlled Jezero HiRISE DTM and its matching orthoimage; preserve product identity and transformations. |
| [Jezero_C DTM metadata](https://asc-pds-services.s3.us-west-2.amazonaws.com/mosaic/mars2020_trn/HiRISE/DTM_MOLAtopography_DeltaGeoid_Jezero_C_Edited_affine_1m_Eqc_latTs0_lon0.xml) | Mars 2000 reference sphere, metre heights/grid, 2020-07-24 product; original sample values may be negative. |
| [ESP_045994_1985 ortho metadata](https://asc-pds-services.s3.us-west-2.amazonaws.com/mosaic/mars2020_trn/HiRISE/ESP_045994_1985_Edited_affine_25cm_Eqc_latTs0_lon0.xml) | A single grayscale band, not RGB true colour. Register by CRS/transform, not by resizing the pixel array. |
| [USGS HiRISE DTM/ortho usability](https://stac.astrogeology.usgs.gov/docs/data/mars/hirise_dtms/) | Post spacing is not resolving power/accuracy; inspect artifacts and image registration. Small rock shape cannot be recovered by upsampling. |
| [USGS 2025 Mars Sample Return release](https://astrogeology.usgs.gov/search/map/mars-sample-return-terrain-relative-navigation-hirise-dtm-mosaic) | New western coverage is valuable for extended traverses, but does not justify silently replacing this matched 2020 pair. Multi-DTM offsets remain relevant. |
| [PROJ equirectangular formulas](https://proj.org/en/stable/operations/projections/eqc.html) | Latitude of true scale matters: the source's lat_ts=0 horizontal grid is distorted at Jezero. |
| [PROJ azimuthal equidistant](https://proj.org/en/stable/operations/projections/aeqd.html) | Use a small local Mars reference-body grid centred on the selected region; do not reuse an Earth EPSG CRS. |
| [Rasterio reprojection](https://rasterio.readthedocs.io/en/stable/topics/reproject.html) | Supply explicit CRS and transforms for source and target arrays. |
| [Rasterio warp API](https://rasterio.readthedocs.io/en/latest/api/rasterio.warp.html) | Disable approximate-transform tolerance for reproducibility; pin the tested 1.5.2 runtime with explicit tolerance support. |
| [GDAL warp resampling factors](https://gdal.org/en/stable/doxygen/structGDALWarpOptions.html) | Point-sampled DEM posts use XSCALE=YSCALE=1. Orthoimages use normal bilinear footprint resampling; these are distinct meanings. |
| [NASA Mars facts](https://science.nasa.gov/mars/facts/) | Mars has a thin dusty atmosphere; a black lunar sky or default Earth sky is not an adequate general visual model. |
| [NASA Mars fact sheet](https://nssdc.gsfc.nasa.gov/planetary/factsheet/marsfact.html) | Gravity varies by location; 3.71 m/s² is nominal. Use nominal 11 km scale height. Solar irradiance is not a direct prescription for an RGB directional light in lux. |
| [NASA Mars sky/sunset explanation](https://science.nasa.gov/solar-system/planets/mars/what-does-a-sunrise-sunset-look-like-on-mars/) | Dust and geometry affect sky colours, including blue near the setting Sun. A single orange RGB tint is not validated atmospheric scattering. |
| [UE 5.7 Landscape technical guide](https://dev.epicgames.com/documentation/en-us/unreal-engine/landscape-technical-guide-in-unreal-engine?application_version=5.7) | Valid component topology, positive scale, vertex/quads distinction and the 1024-component performance ceiling. |
| [UE heightmap import](https://dev.epicgames.com/documentation/en-us/unreal-engine/importing-and-exporting-landscape-heightmaps-in-unreal-engine?application_version=5.7) | Preserve XY/Z physical scales and use 16-bit heights; increasing image dimensions alone creates no measured detail. |
| [UE 5.7 SkyAtmosphere properties](https://dev.epicgames.com/documentation/en-us/unreal-engine/sky-atmosphere-component-properties-in-unreal-engine?application_version=5.7) | Radius/altitudes are in kilometres; source reference radius replaces Earth radius. Disable the default Earth ozone absorption layer. |
| [UE 5.7 PostProcessSettings](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PostProcessSettings?application_version=5.7) | Lock min/max exposure consistently with this project's extended luminance range; avoid an undisclosed changing exposure during comparisons. |
| [UE 5.7 MaterialEditingLibrary](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/MaterialEditingLibrary?application_version=5.7) | Create explicit graphs, check connection results and save generated assets separately. A successful graph call is not proof of correct GPU appearance. |
| [UE Substrate overview](https://dev.epicgames.com/documentation/en-us/unreal-engine/overview-of-substrate-materials-in-unreal-engine?application_version=5.7) | This project enables Substrate. The generated material must be compiled/visually checked in the actual engine; material_path provides an override. |
| [UE 5.7 editor loading/saving](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/EditorLoadingAndSavingUtils?application_version=5.7) | Refuse dirty editor work; create a new world and defer saving until data readback succeeds. |
| [UE Python keep-alive](https://dev.epicgames.com/documentation/en-us/unreal-engine/BlueprintAPI/EditorScripting/Python/SetKeepPythonScriptAlive?application_version=5.7) | Dedicated script execution must stay alive for deferred callbacks; process exit alone is not acceptance. |

## Implemented corrections from review

1. The first increment mapped equatorial grid metres directly to the scene.
   At this Jezero latitude the east-west reference-sphere ground/grid factor
   is approximately 0.9487174. Reprojection now produces a genuinely local
   metric reference grid; finer geoid/altitude effects remain below source accuracy.
2. Earth rasters could pass the earlier generic projected-metre check. Mars
   reference-body radii are now checked explicitly. NaN transforms also fail early.
3. File hashes did not protect against an accidentally edited Z scale/offset
   in the manifest itself. The validator now reconstructs the actual elevation
   samples and compares them against the CSV within quantization error.
4. A pending callback could save after switching worlds or allow concurrent
   builds. World/Play checks and a pending-operation guard now prevent that.
5. The initial scene always required the reference rover. Environment creation
   is now independent; rover loading is optional.
6. Python editor plugins were implicit/manual in the inherited project.
   Required plugins are now explicitly enabled in the project descriptor.
7. Orbital pixels contain the original lighting. They are now an unlit,
   grayscale reference mode, separate from dynamic, explicitly synthetic shading.
8. The old fog-only preview was not a planetary atmosphere. SkyAtmosphere now
   uses Mars radius/nominal scale height and no Earth ozone, while remaining
   clearly labelled as a non-calibrated rendering preset.
9. Actual Windows CI exposed CRLF rewriting of hash-protected CSV data.
   Byte-preserving Git attributes and explicit LF generation now cover Windows
   checkout and regeneration; hashes remain strict.

## Deliberate limits

The second review is documented in [the scientific review](mars-scientific-review.md).
It adds the actual source observation/catalogue, the original FGDC XML files,
Sutton et al. (2022) on effective DTM resolution, Bell et al. (2022) on Jezero
880 nm opacity, Clancy et al. (2003) on solar-band dust SSA, the MEDA archive,
the IAU solar-radius convention, Epic's collision API and NASA-AMMOS Landform.
Published ranges are scenario context; no wavelength/sol-specific measurement
is fabricated. Gas and aerosol distribution heights are separate parameters.
The apparent solar disk is computed from nominal Mars–Sun distance. Removed
local height datum is also applied to the atmosphere's bottom radius.

The offline source audit now checks every terrain post. The native editor
acceptance path requires sampled simple/complex collision before saving,
alongside heightmap readback. This path has not run without an installed UE.

No small collision rocks, false microtopography or recovered material classes
are presented as measured Jezero features. The colour/noise material adds only
synthetic shading variation. The local planar terrain does not model spherical
curvature displacement, loose-regolith sinkage, thermal dynamics or dust physics.

The 252 m reference-body scene neglects only about 4.7 mm maximum spherical sag
at its corners, but source stereo/datum errors can be metres. GPU image quality,
Substrate compilation and camera response still need actual Windows UE 5.7
acceptance. Passing Python tests is not substituted for those measurements.
