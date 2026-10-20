# Setup in detail

This folder **is** the plugin — copy it whole.

1. **Prerequisite (one-time):** Visual Studio 2022 with the *Game development
   with C++* workload.
2. Close the Unreal editor. In your Unreal **project** folder (next to the
   `.uproject`), create `Plugins/` if needed and copy this folder in:

   ```
   <YourProject>/Plugins/UnrealSPADCam/
   ├── UnrealSPADCam.uplugin
   ├── LICENSE
   └── Source/UnrealSPADCam/
       ├── UnrealSPADCam.Build.cs
       ├── Public/UnrealSPADCam.h
       └── Private/{UnrealSPADCam.cpp, UnrealSPADCamModule.cpp}
   ```

3. Open the `.uproject`. Answer **Yes** to rebuild `UnrealSPADCam`.
4. Confirm it under **Edit → Plugins → Project → Other → Unreal SPAD Cam**.
5. Add a **SceneCaptureComponent2D** named **`SPADCam`** where the sensor should
   sit. Give it a **TextureRenderTarget2D** (or leave it empty and one is
   auto-created at `CaptureWidth`×`CaptureHeight`, default 256×256).
6. Add the **UnrealSPADCam** component to any actor. If you used the name above
   nothing needs configuring; otherwise set **CaptureName** to your component. At
   Play it logs the capture it found and the address it streams to.
