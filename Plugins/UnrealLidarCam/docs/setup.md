# Setup in detail

## Installing

1. Copy this folder to `<Project>/Plugins/UnrealLidarCam`.
2. Open the project; Unreal asks to build the missing `UnrealLidarCam` module: accept
   (needs the Visual Studio C++ tools). Or build from the command line with the
   editor closed.

## Adding it to the rover

Add a **Unreal Lidar Cam** component to the rover blueprint (Add → *Unreal Lidar Cam*). Then
either:

- **attach it under a camera** in the component tree (e.g. drag it onto
  `Navcam_Center`): it scans from where it sits, its +X is the scan's centre; or
- leave it anywhere and pick the camera in **Follow Component Name** (dropdown of
  the actor's cameras and scene captures): it scans from that camera's pose every
  frame, so it shares the camera's view. With the same aperture as the camera
  (90 x 73.7 degrees for the 640 x 480, 90-degree navcams) its points cover the
  image.

It ignores the actor carrying it (the rover) by default.
