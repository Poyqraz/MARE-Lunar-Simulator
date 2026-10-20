# Component parameters

**SPADCam | Network**
- `ServerIp` / `ServerPort` — where `component_spad_camera` listens (default
  `127.0.0.1:3006`; only `127.0.0.1` crosses into WSL under mirrored networking).
- `CamId` — id stamped in every packet.

**SPADCam | Camera**
- `CaptureName` — the SceneCapture2D to render from (dropdown).
- `CaptureWidth` / `CaptureHeight` — render-target size if none is assigned.
- `MaxSampleHz` — cap on how often frames are sampled and sent (0 = every
  rendered frame), per simulated (game) second. The SPAD exposure / photon
  parameters are set on the ROS side.
