# Component parameters

**EventCam | Network**
- `ServerIp` / `ServerPort` — where the ROS event node listens (default
  `127.0.0.1:3005`; only `127.0.0.1` crosses into WSL under mirrored networking).
- `CamId` — id stamped in every packet, so several event cameras share a consumer.

**EventCam | Camera**
- `CaptureName` — the SceneCapture2D to render from (dropdown).
- `CaptureWidth` / `CaptureHeight` — render-target size if none is assigned. Keep
  modest; the model is O(W·H) per frame on the CPU.
- `MaxSampleHz` — cap on how often frames are sampled for events (0 = every
  rendered frame). Higher is better for event fidelity. Per simulated (game)
  second, so it holds when the editor runs below real time.

**EventCam | Model** (ESIM)
- `ContrastThresholdPos` / `ContrastThresholdNeg` — C+ / C- in log-intensity
  units. Real DVS pixels sit around 0.1–0.5; larger = fewer events.
- `SigmaThresholdPos` / `SigmaThresholdNeg` *(advanced)* — Gaussian noise on the
  thresholds (pixel mismatch). 0 disables.
- `RefractoryPeriodMs` *(advanced)* — per-pixel dead time after firing. 0 disables.
- `bUseLogImage` *(advanced)* — operate on log intensity (the physical model);
  leave on outside debugging.
