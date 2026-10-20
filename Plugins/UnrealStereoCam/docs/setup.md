# Setup in detail

This folder **is** the plugin — copy it whole.

1. **Prerequisite (one-time):** a C++ toolchain. Install **Visual Studio 2022
   Community** with the *Game development with C++* workload. Needed even for
   a Blueprint-only project: code plugins are compiled against your engine
   when the editor first loads them.
2. Close the Unreal editor. In your Unreal **project** folder (next to the
   `.uproject`), create a `Plugins` directory if it does not exist, and copy
   this folder into it:

   ```
   <YourProject>/Plugins/UnrealStereoCam/
   ├── UnrealStereoCam.uplugin
   └── Source/UnrealStereoCam/
       ├── UnrealStereoCam.Build.cs
       ├── Public/UnrealStereoCam.h
       └── Private/{UnrealStereoCam.cpp, UnrealStereoCamModule.cpp}
   ```

3. Open the `.uproject`. The editor reports *"The following modules are
   missing or built with a different engine version: UnrealStereoCam. Would
   you like to rebuild them now?"* — answer **Yes**. It compiles in a minute
   or two and the editor opens. (If it fails, the build log is at
   `<YourProject>/Saved/Logs/UnrealBuildTool/`; the usual cause is the C++
   workload missing from Visual Studio.)
4. Confirm it's active under **Edit → Plugins → Project → Other →
   Unreal Stereo Cam** (enabled by default).
5. Add three **SceneCaptureComponent2D** components named exactly
   **NavcamLeft**, **NavcamRight**, **NavcamCenter**, posed like the three
   navcams (left, right and centre of the stereo rig). Give each a
   **TextureRenderTarget2D** (640×480, RTF RGBA8). They can live on any actor
   — the rover pawn is the natural home so they move with it.
6. Add the **UnrealStereoCam** component to any actor (the rover pawn is fine;
   it appears in the *Add Component* search once the plugin is built). The
   captures are selected **by component name** — no pickers, no actor linking.
   Its own actor is searched first, then the whole world. If you used the
   names above, nothing needs configuring; otherwise set
   `Left/Right/CenterCaptureName` to match your components tree. At Play, the
   Output Log prints one line per camera saying what was found and on which
   actor — or lists every SceneCapture2D in the world if a name matches
   nothing.

   The cam ids sent to ROS default to left 1, right 2, centre 0, matching
   `left/right/center_camera_id` in
   `component_stereo_depth/config/params.yaml`; they are under the details
   panel's *Advanced* arrow if you ever change those.
7. Leave `ServerIp` at `127.0.0.1`, `ServerPort` at 3004. `SendHz` 5 is ample
   for the 1 Hz stereo pipeline. Rates are per simulated (game) second, so they
   hold relative to physics and `/clock` when the editor runs below real time.
8. On the ROS side set `image_source: stream` in the stereo node's params and
   restart it. Start order does not matter — the node listens and Unreal
   connects at BeginPlay (re-Play after restarting the node, as with the rover
   link).

The rig geometry comes from the node's `baseline_m` / `hfov_deg` params;
colour and the object mask come from the captures below.
