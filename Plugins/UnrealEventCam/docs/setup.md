# Setup in detail

This folder **is** the plugin — copy it whole.

1. **Prerequisite (one-time):** Visual Studio 2022 with the *Game development
   with C++* workload (code plugins are compiled against your engine).
2. Close the Unreal editor. In your Unreal **project** folder (next to the
   `.uproject`), create `Plugins/` if needed and copy this folder in:

   ```
   <YourProject>/Plugins/UnrealEventCam/
   ├── UnrealEventCam.uplugin
   ├── LICENSE
   └── Source/UnrealEventCam/
       ├── UnrealEventCam.Build.cs
       ├── Public/{UnrealEventCam.h, EventSimulator.h}
       └── Private/{UnrealEventCam.cpp, EventSimulator.cpp, UnrealEventCamModule.cpp}
   ```

3. Open the `.uproject`. Answer **Yes** to rebuild `UnrealEventCam`. It compiles
   in a minute or two. (Build log on failure:
   `<YourProject>/Saved/Logs/UnrealBuildTool/`.)
4. Confirm it under **Edit → Plugins → Project → Other → Unreal Event Cam**
   (enabled by default).
5. Add a **SceneCaptureComponent2D** named **`EventCam`** where the sensor should
   sit (the rover pawn is fine — it moves with the actor). Give it a
   **TextureRenderTarget2D** (or leave it empty and one is auto-created at
   `CaptureWidth`×`CaptureHeight`, default 346×260 — a DAVIS-346 resolution).
6. Add the **UnrealEventCam** component to any actor. If you used the name above
   nothing needs configuring; otherwise set **CaptureName** to your component.
   At Play it logs the capture it found and the address it streams to.
