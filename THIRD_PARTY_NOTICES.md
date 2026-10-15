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
| `Plugins/TAPython` | TAPython by Chen Huipeng | its author's terms (not covered by this project's licence) |
| Unreal Engine and its engine content | Epic Games | [Unreal Engine EULA](https://www.unrealengine.com/eula) |

Required attribution for the Yutu model (CC-BY-4.0):

> This work is based on "Yutu"
> (https://sketchfab.com/3d-models/yutu-d9564c9a60c14b85a880cc0bfcf1a6b5) by
> tashtego (https://sketchfab.com/tashtego) licensed under CC-BY-4.0
> (http://creativecommons.org/licenses/by/4.0/).

The Poly Haven assets are CC0 and need no attribution; they are credited here
as a courtesy.
