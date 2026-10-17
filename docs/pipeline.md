# The pipeline

![The pipeline](images/pipeline.svg)

MARE runs on one Windows machine: Terrain Studio and the Unreal Editor on
Windows, the GNC stack in Docker containers in WSL2. Every link between them
goes through `127.0.0.1`.

## 1. Build the world (Terrain Studio)

[Terrain Studio](https://github.com/raulcastar/Unreal-Moon-Terrain-Generation)
is a desktop app that talks to the open editor through Unreal's Python Remote
Execution. Its home screen lays out the steps in order:

| Step | In the studio | In Unreal |
|---|---|---|
| **Terrain** | Generate a DEM with craters (or load a real one: `.tif`, `.npy`, `.csv`) | A Landscape from its 16-bit heightmap, with the project's material, tagged for the object mask |
| **Rocks** | Plan a rock field: lunar size distribution, kept off the rover corridors and the crater bowls | One instanced actor with the Poly Haven rocks, each tagged boulder or small rock |
| **Masks** | Crater ids, shadow, sun, wheel-track and rover-shadow classes | The crater-id texture and the ground-truth post-process material read by the object-mask camera |
| **Sun** | Pick the azimuth and elevation, with the cast shadows predicted on the DEM | The directional light and the sun parameters the masks use |

The studio writes everything for a map to `outputs/<name>/`. Two of those files
are also the GNC planner's global map: `<name>_elevationMap.csv` and
`<name>_soilMap.csv` (step 3).

The same steps run from the command line or through the studio's MCP server.

## 2. Simulate and render (Unreal)

The level holds the Landscape, the rocks, the sun and a rover Blueprint
(`Leo_Raph` or `Yutu_Rover`). In Play:

- **The rover** is a physics body on driven wheel constraints. Its Blueprint connects to the GNC rover node over TCP (TCP-Unreal plugin) at BeginPlay, receives wheel speeds and the headlights, and sends its pose back.
- **The sensor plugins** are components on the rover. Each renders its own captures and streams them to its GNC node:

| Plugin | Data | Port | GNC node |
|---|---|---|---|
| — (rover Blueprint) | wheel commands out, pose telemetry in | 3003 | `component_rover_leo_raph` |
| UnrealStereoCam | navcams (left, central, right), ground-truth depth, object mask, rear camera | 3004 | `component_stereo_depth` |
| UnrealEventCam | brightness-change events (ESIM) | 3005 | `component_event_camera` |
| UnrealSPADCam | intensity frames for the photon model | 3006 | `component_spad_camera` |
| UnrealLidarCam | lidar scans | 3007 | `component_lidar` |
| UnrealSimClock | simulation time | 3008 | `component_sim_clock` |

In every link **Unreal dials and the container listens**. The plugins redial
until their node is up; the rover connects once per Play.

- **Ground truth** comes with the images: depth in metres, and an object mask in which every pixel carries a class (landscape, crater, crater rim, boulder, small rock, wheel track, rover, sun…) plus a shadow bit. Terrain Studio sets these classes up; the ids are in its [masks docs](https://github.com/raulcastar/Unreal-Moon-Terrain-Generation/blob/main/docs/masks.md#object-mask-ids).
- **Editor Python** runs alongside: the Terrain Studio watcher keeps the masks aligned with the sun and lays wheel tracks during Play, and the viewport camera follows what mission control asks for (follow, orbit, top-down).

The navcams and the rear camera each have both masks. The shadow mask labels sky, sunlit and shadowed ground, sunlit and shadowed objects, and the rover's own shadow:

![Front and rear cameras with their object and shadow masks](images/ground_truth.webp)

*The front navcam and the rear camera during a drive, with their ground-truth object
masks and shadow masks (2.4x speed; [video](videos/ground_truth.mp4) at 1.2x). Ahead, the rover's own
shadow (orange) is labelled apart from the terrain's shadows; behind, the wheel
tracks it leaves are their own class in the object mask.*

## 3. Drive (GNC stack)

[GNC-Moon-Simulator](https://github.com/raulcastar/GNC-Moon-Simulator) runs one
ROS 2 Jazzy node per container:

1. **Perception:** stereo depth (SGBM) from the navcams, the object and shadow masks, a local elevation map, the lidar point cloud, a simulated IMU, and the event and SPAD cameras.
2. **Planning:** the global route is planned with fast marching on the DEM and soil map from Terrain Studio (copied to `component_path_planner/maps/`); a DWA local planner follows it, avoiding the obstacles the lidar sees.
3. **Control:** the rover node ramps `/cmd_vel` into skid-steer wheel speeds and sends them to Unreal; the pose that comes back becomes `/odom` and TF.

Mission control (http://127.0.0.1:5000) shows all of it and sends the goals;
it also records and replays rosbags, and its JSON API (port 5001) and MCP
server expose the same controls to scripts and AI agents.

## Time

Everything runs on **Unreal's simulation time**. Each plugin stamps its data at
capture; UnrealSimClock streams the same clock to `/clock`; the GNC nodes run
with `use_sim_time`. A slow frame or a paused Play slows the stack with it, and
a recorded bag replays with the stamps the sensors saw.

## Coordinates

| | Unreal | ROS (REP-103) | Terrain Studio maps |
|---|---|---|---|
| Axes | left-handed, x forward, z up | right-handed, x forward, y left, z up | rows and columns of the DEM |
| Units | cm, degrees | m, radians | m (`RESOLUTION_M_PER_PX` per cell) |

The rover node converts Unreal's pose to REP-103 (`odom → base_link`).

## A full run

1. Open the Unreal project and a level (`Lunar_Terrain_Raph` to start).
2. *Optional:* in Terrain Studio, generate a terrain and send it to Unreal, place its rocks, send the masks and set the sun; copy the map's elevation and soil CSVs to the planner's `maps/` and name them in its `config/params.yaml`.
3. Start the GNC stack (`./docker_build.sh` the first time, then `docker compose up -d`).
4. Press **Play**. The rover lands and settles in a few seconds.
5. In mission control, click on the map to send a goal; watch the drive, and record a bag of the sensors if you need the data.
