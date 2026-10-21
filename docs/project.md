# The Unreal project

`Moon_Simulator.uproject`, Unreal Engine 5.7.

## Levels

| Level | What it is |
|---|---|
| `Lunar_Terrain_Raph` | The default level (editor and game): Leo_Raph |
| `Lunar_Terrain_Yutu` | The same level with Yutu |

Both rover levels share one terrain: the Landscape `procedural_lunar_terrain_elevationMap_heightmap`
and the rock field `procedural_lunar_terrain_1_2_rocks`, the terrain the GNC
planner's default maps (`procedural_lunar_terrain_1_elevationMap_2.csv` and its
soil map) and the crater map describe. Keep them in step: a level on a
different terrain needs its own planner maps and its own crater map (see
[the crater map](#the-crater-map-is-shared)).

The GNC stack drives one rover at a time; open the rover's level and choose the
same rover in mission control (see
[switching rovers](https://github.com/raulcastar/GNC-Moon-Simulator/blob/main/docs/rovers.md#leo_raph-and-yutu)).

## Rovers

| | Leo_Raph | Yutu |
|---|---|---|
| Based on | Fictionlab's [Raph Rover](https://fictionlab.pl/raph-rover/) | "Yutu" by tashtego (Sketchfab, CC-BY-4.0) |
| Blueprint | `Content/Blueprints/Leo_Raph` | `Content/Blueprints/Yutu_Rover` |
| Meshes, materials | `Content/RoverAssets/Leo_Raph` | `Content/RoverAssets/Yutu` |
| Wheels | 4 | 6 (rigid chassis) |
| Sensors | on the body, 0.55 m up | on the mast, 1.13 m up |

Both Blueprints have the same graph: the TCP link to the GNC rover node, pose
telemetry, headlights and the sensor components. `Yutu_Rover` started as a copy
of `Leo_Raph`; the GNC docs describe
[how it was built](https://github.com/raulcastar/GNC-Moon-Simulator/blob/main/docs/rovers.md#adding-a-rover-how-yutu-was-built),
and `Content/RoverAssets/Yutu/Source/` holds the Blender script that prepared
the model. `Content/Blueprints/WheelPhysics` is the wheels' physical material.

## Plugins

| Plugin | Role |
|---|---|
| [UnrealStereoCam](https://github.com/raulcastar/UnrealStereoCam) | Navcams (left, central, right), ground-truth depth, object mask, rear camera |
| [UnrealLidarCam](https://github.com/raulcastar/UnrealLidarCam) | Lidar with a configurable aperture (GPU depth captures or line traces) |
| [UnrealEventCam](https://github.com/raulcastar/UnrealEventCam) | Event camera: brightness-change events from rendered frames (ESIM) |
| [UnrealSPADCam](https://github.com/raulcastar/UnrealSPADCam) | Intensity frames for the SPAD photon model |
| [UnrealSimClock](https://github.com/raulcastar/UnrealSimClock) | Simulation time for every plugin, streamed to `/clock` |
| [TCP-Unreal](https://github.com/getnamo/TCP-Unreal) | The rover Blueprint's TCP link (third party, MIT) |
| [UnrealDEMLandscape](https://github.com/raulcastar/UnrealDEMLandscape) | Creates Landscapes from heightmaps in editor Python, for Terrain Studio (see [setup](setup.md#unrealdemlandscape)) |

The sensor plugins here are copies of their repositories; changes are made
there and copied in.

## Content

| Folder | Contents |
|---|---|
| `Blueprints/` | The rover Blueprints and the wheel physical material |
| `RoverAssets/` | Rover meshes and materials (Leo_Raph; Yutu, CC-BY-4.0) |
| `Landscape/` | The Landscape material, its Poly Haven textures, and the rocks as foliage types |
| `LunarRocks/` | The Poly Haven rocks as imported by Terrain Studio for its rock fields |
| `GroundTruth_Masks/` | The ground-truth mask material, crater-id maps, the sun's parameters, the rover-shadow render target, the wheel-track decal |
| `Effects/LunarDust/` | A Niagara system for lunar dust |
| `Python/` | Editor scripts (below) |

## Editor Python

| Script | Runs | Does |
|---|---|---|
| `init_unreal.py` | when the editor opens | Starts the Terrain Studio watcher from `Python/TerrainStudio/` (masks follow the sun, wheel tracks during Play, the rover-shadow helper) |
| `rover_cameras_startup.py` | project startup script | Starts the link to mission control for the viewport camera |
| `rover_cameras.py` | from either | Follow, orbit and top-down viewport cameras; also callable from the Output Log (`import rover_cameras as rc; rc.orbit()`) |

Terrain Studio refreshes `Python/TerrainStudio/` whenever it sends to Unreal.

## The crater map is shared

The object mask's craters come from one material, `GroundTruth_Masks/Mask/PPM_GroundTruthMask`,
which holds a single crater map (`GroundTruth_Masks/CraterMaps/T_CraterIds_<map>`)
and its placement. Terrain Studio's **Send Masks to Unreal** rewrites both for
the map it sends, so it changes the craters in **every** level. Today the two
rover levels share the `_1_2` map. After sending masks for
another terrain, send the original map again (or keep that work in a separate
project) before recording ground truth in these levels; rocks, the rover and
wheel tracks are tagged per actor and are not affected.

## Settings

From `Config/DefaultEngine.ini`:

| Setting | Value | Why |
|---|---|---|
| Gravity | −980 cm/s² (Earth) | The rover is much easier to control than under the Moon's −162; the drive tuning that goes with it is in the [GNC rover docs](https://github.com/raulcastar/GNC-Moon-Simulator/blob/main/docs/rovers.md#gravity) |
| Physics substepping | on, ≤ 8.3 ms, up to 8 substeps; enhanced determinism | Stable wheel constraints at any frame rate |
| Global illumination, reflections | Lumen | No baked lighting: the sun can move |
| Shadows | virtual shadow maps | Sharp, long shadows from a low sun |
| Custom depth | enabled with stencil | The object mask reads the stencil ids |
| Python Remote Execution | on, `239.0.0.1:6766` on `127.0.0.1` | Terrain Studio and the GNC tools drive the editor |

The editor and the game both open `Lunar_Terrain_Raph`.
