# Third-party content

The Moon Simulator Unreal project is MIT licensed, © 2026 Raul Castilla
Arquillo (see [LICENSE](LICENSE)), except the content listed here, which keeps
its own licence. The ROS 2 stack that drives it is
[GNC-Moon-Simulator](https://github.com/raulcastar/GNC-Moon-Simulator) and the
terrain, rock and ground-truth tools are
[Unreal-Moon-Terrain-Generation](https://github.com/raulcastar/Unreal-Moon-Terrain-Generation)
(Terrain Studio).

| Content | Source | Licence |
|---|---|---|
| `Content/Landscape/Assets/moon_01_4k`, `moon_02_4k`, `moon_03_4k` (landscape textures) and `moon_rock_01_1k` … `moon_rock_07_1k`; `Content/LunarRocks` (the same rocks, imported by Terrain Studio) | [Poly Haven, Moon collection](https://polyhaven.com/collections/moon) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) (public domain) |
| `Content/RoverAssets/Yutu` (Yutu rover model) | "Yutu" by [tashtego](https://sketchfab.com/tashtego) on [Sketchfab](https://sketchfab.com/3d-models/yutu-d9564c9a60c14b85a880cc0bfcf1a6b5) | [CC-BY-4.0](http://creativecommons.org/licenses/by/4.0/), credited in `Content/RoverAssets/Yutu/CREDITS.txt` and `license.txt` |
| `Plugins/TCP-Unreal` | [TCP-Unreal](https://github.com/getnamo/TCP-Unreal) by Jan Kaniewski (getnamo) | MIT, see `Plugins/TCP-Unreal/LICENSE` |
| `Plugins/UnrealEventCam`: the event model (`EventSimulator.h/.cpp`) | port of ESIM ([rpg_esim](https://github.com/uzh-rpg/rpg_esim)), Robotics and Perception Group, University of Zurich | MIT, see `Plugins/UnrealEventCam/LICENSE` |
| `Plugins/UnrealSPADCam`: the frames it streams feed a SPAD photon model ported from [spadSim](https://github.com/drodriguezSRL/spadSim) by David Rodriguez-Martinez; the port itself lives in [GNC-Moon-Simulator](https://github.com/raulcastar/GNC-Moon-Simulator) (`component_spad_camera`) | [spadSim](https://github.com/drodriguezSRL/spadSim) | MIT, © 2025 David Rodriguez-Martinez, see `Plugins/UnrealSPADCam/LICENSE` |
| Unreal Engine and its engine content | Epic Games | [Unreal Engine EULA](https://www.unrealengine.com/eula) |

Required attribution for the Yutu model (CC-BY-4.0):

> This work is based on "Yutu"
> (https://sketchfab.com/3d-models/yutu-d9564c9a60c14b85a880cc0bfcf1a6b5) by
> tashtego (https://sketchfab.com/tashtego) licensed under CC-BY-4.0
> (http://creativecommons.org/licenses/by/4.0/).

The Poly Haven assets are CC0 and need no attribution; they are credited here
as a courtesy.

## Jezero starter terrain added in this fork

`Content/Mars/Jezero/` contains a locally reprojected 253 × 253 grid from the USGS
Mars 2020 HiRISE DTM **Jezero_C**, published 2020-07-24. Originators listed in
the source metadata: Robin Fergason, Donna Galuszka, Trent Hare, David Mayer,
Bonnie Redding and Ethan Smith. HiRISE instrument: NASA/JPL/University of Arizona.

The [source metadata](https://asc-pds-services.s3.us-west-2.amazonaws.com/mosaic/mars2020_trn/HiRISE/DTM_MOLAtopography_DeltaGeoid_Jezero_C_Edited_affine_1m_Eqc_latTs0_lon0.xml)
lists access and use constraints as **None**. Source data are credited here;
they are not relicensed as original MIT software. The bundled manifest records
the original URL, CRS, pixel window, scale, offset, transformations and output
checksums. A registered grayscale orbital reference from the paired
ESP_045994_1985 image is also included; it is not RGB true colour or albedo.
Full source and transformation notes are in
[DATA_SOURCES.md](Content/Mars/Jezero/DATA_SOURCES.md).

The exact original USGS FGDC metadata snapshots are included as
`source_dem.xml` and `source_ortho.xml`. The review figure
`docs/images/jezero-fidelity.png` plots these derived USGS/HiRISE data;
it is not an Unreal render or a newly acquired Mars image.

`docs/images/jezero-navigation.png` is another derived USGS/HiRISE plot, with
offline geometric routes and a blocked mask. It is not an Unreal render or
an actual rover traverse. The same source attribution above applies.

## Navigation method references and optional dependency

The starred repository review in `docs/mars-starred-review.md` and its JSON
inventory records method references and license metadata. No source code,
models, weights, calibration files or assets from those starred projects were
copied into this fork. Standard A*, rigid transforms, terrain tests and route
tracking were implemented independently here.

Optional stereo mode calls [OpenCV](https://opencv.org/) through the pinned
`opencv-python-headless` package; OpenCV 4.5+ uses the
[Apache 2.0 license](https://opencv.org/license/). The wheel is installed as
a dependency, not vendored in this repository; its included third-party
notices remain applicable. Stereo method documentation:
[StereoSGBM](https://docs.opencv.org/4.x/d2/d85/classcv_1_1StereoSGBM.html).
