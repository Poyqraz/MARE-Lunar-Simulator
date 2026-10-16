# Setup

## Clone

The levels and assets are stored with [Git LFS](https://git-lfs.com). Install it
before cloning, or the `.uasset` and `.umap` files arrive as small text
pointers that Unreal cannot open:

```sh
git lfs install
git clone https://github.com/raulcastar/MARE-Lunar-Simulator.git
```

In a clone made without LFS, run `git lfs pull`.

## Unreal Engine and the plugins

The project targets **Unreal Engine 5.7** on Windows. The sensor plugins and
TCP-Unreal are in `Plugins/` as source; their binaries are not in the
repository.

- **Build on open (default):** install Visual Studio 2022 with the *Game development with C++* workload, open `Moon_Simulator.uproject`, and answer **Yes** when Unreal offers to rebuild the missing modules.
- **Prebuilt:** each sensor plugin's repository has a release for UE 5.7 Win64. Extract it over the plugin's folder in `Plugins/` (this replaces the source copy with the same version).

Engine plugins the project needs are enabled in the `.uproject` and the
plugins' own descriptors: Python Editor Script Plugin, Editor Scripting
Utilities, Modeling Tools, Json Blueprint Utilities, Procedural Mesh and
Geometry Scripting.

## TAPython

Terrain Studio builds Landscapes through
[TAPython](https://github.com/cgerchenhp/UE_TAPython_Plugin_Release) 1.3.1, a
plugin distributed only as binaries. Its UE 5.7 Win64 build is in
`Plugins/TAPython/Binaries/` (the only plugin binaries in the repository), and
its configuration and Python folder in `TA/TAPython/`; it needs no setup.

The binaries match the engine build they were made for. If Unreal reports
TAPython as built for a different engine version, download the release for
your engine from TAPython's releases page and replace
`Plugins/TAPython/Binaries/` with its `Binaries/`.

Without TAPython the project still opens and simulates; only Terrain Studio's
Landscape import needs it.

## Project settings worth checking

They are set in `Config/DefaultEngine.ini`; check them after cloning:

- **Python → Remote Execution** on, multicast group `239.0.0.1:6766` bound to `127.0.0.1`: Terrain Studio and the GNC tools reach the editor this way.
- **Python → Startup Scripts**: `rover_cameras_startup.py` (the viewport camera follows mission control). `Content/Python/init_unreal.py` runs by itself and starts the Terrain Studio watcher.

## The rest of the suite

| | Where | Needs |
|---|---|---|
| GNC stack | [GNC-Moon-Simulator](https://github.com/raulcastar/GNC-Moon-Simulator) | WSL2 with mirrored networking, Docker; ROS 2 Jazzy runs in the containers |
| Terrain Studio | [Unreal-Moon-Terrain-Generation](https://github.com/raulcastar/Unreal-Moon-Terrain-Generation) | Python 3 with Tkinter; the editor open |

Clone them next to this one. Nothing in this project depends on where they
are: they connect to the editor over `127.0.0.1`.

## First run

1. Open `Moon_Simulator.uproject`; it opens on `Lunar_Terrain_Raph`.
2. Start the GNC stack (`./docker_build.sh` in GNC-Moon-Simulator).
3. Press **Play**. Within a few seconds the dashboard at http://127.0.0.1:5000 shows the navcams and the rover's pose.
4. Click on the overview map to send a goal.

If a feed stays dark, the [links and ports](https://github.com/raulcastar/GNC-Moon-Simulator/blob/main/docs/unreal.md#links-and-ports)
section of the GNC docs lists what each one needs.
