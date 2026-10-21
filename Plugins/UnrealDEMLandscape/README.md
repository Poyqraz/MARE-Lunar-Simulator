# UnrealDEMLandscape

[![Part of MARE](https://img.shields.io/badge/Part%20of-MARE-e8a33d)](https://github.com/raulcastar/MARE-Lunar-Simulator)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Unreal Engine 5.7](https://img.shields.io/badge/Unreal%20Engine-5.7-313131?logo=unrealengine&logoColor=white)](https://www.unrealengine.com/)

Creates Unreal Engine Landscapes from digital elevation models (DEMs) in editor
Python. Unreal's Python API cannot create a Landscape's components, so this
small editor plugin does what the editor's *New Landscape* tool does: it spawns
the Landscape with the layout you choose and imports a 16-bit heightmap in the
same step. It also reads the heights back, to check an import.

Part of [MARE](https://github.com/raulcastar/MARE-Lunar-Simulator), an open-source lunar rover
simulation suite, where
[Terrain Studio](https://github.com/raulcastar/Unreal-Moon-Terrain-Generation) uses it to
build the Landscape of every generated or real lunar terrain.

## Requirements

Unreal Engine 5.7 on Windows (the version it is developed and tested with), with
the *Python Editor Script Plugin* enabled to call it from Python. Building from
source also needs Visual Studio 2022 with the *Game development with C++*
workload.

## Install

- **Prebuilt (UE 5.7, Win64):** download `UnrealDEMLandscape-<version>-UE5.7-Win64.zip`
  from [Releases](https://github.com/raulcastar/UnrealDEMLandscape/releases) and extract it
  into `<YourProject>/Plugins/`.
- **From source:** clone this repository into `<YourProject>/Plugins/UnrealDEMLandscape`,
  open the project and answer **Yes** to rebuild the module.

Then check it is enabled under *Edit → Plugins → Project → Editor*.

## Use

```python
import unreal

lib = unreal.DEMLandscapeLibrary
# 16 x 16 components of 1 section of 63 quads: 16 * 63 + 1 = 1009 x 1009 vertices,
# so moon.r16 must hold 1009 * 1009 little-endian 16-bit heights, row by row.
landscape = lib.create_landscape(
    unreal.Transform(location=[0, 0, 0], rotation=[0, 0, 0], scale=[100, 100, 100]),
    section_size=63, sections_per_component=1,
    component_count_x=16, component_count_y=16,
    heightmap_file="C:/terrains/moon.r16")      # "" for a flat Landscape

heights = lib.get_heightmap_data(landscape)     # 1009 * 1009 values, row by row
```

- **Layout:** `section_size` is the quads per section (7, 15, 31, 63, 127 or 255)
  and `sections_per_component` is 1 or 2, as in the *New Landscape* tool.
- **Scale and heights:** the transform's scale sets the vertex spacing in X and
  Y (cm) and the height scale in Z: a vertex's height is
  `(h - 32768) * scale.z / 128` cm above the actor, `h` being its 16-bit value.
- **Errors:** an unreadable or mis-sized heightmap returns `None`, with the
  reason in the Output Log (`LogDEMLandscape`).
- **Undo:** the creation is one editor transaction.

The functions are also Blueprint nodes (*DEM Landscape* category) in editor
utility Blueprints.

## Dependencies

None: only engine modules.

## Docs

| | |
|---|---|
| [Making a release](docs/release.md) | Building the prebuilt zip for GitHub releases |

## License

[MIT](LICENSE), © 2026 Raul Castilla Arquillo.
