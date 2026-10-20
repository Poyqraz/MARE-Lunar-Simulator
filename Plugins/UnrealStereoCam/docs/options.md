# Options

## Ground-truth depth (on by default)

With **Stream Center Depth** (`bStreamCenterDepth`, Details → *StereoCam |
Cameras*), the component also streams Unreal's own depth for the central camera.
At Play it adds a depth-only `SceneCaptureComponent2D` attached to the centre
capture, with its projection, FOV, resolution and hidden / show-only actors, so
it sees exactly the same view; nothing has to be added to the blueprint. Each
pixel is the scene depth in centimetres along the camera axis (planar depth),
sent as float on **DepthCamId** (default 4, under *Advanced*; must match
`depth_ground_truth_camera_id` in `component_stereo_depth/config/params.yaml`).

The stereo node publishes it as `navcam/central/depth_ground_truth` (32FC1,
metres, +Inf for the sky) and `.../visualization`, with the same stamp and frame
as `image_color` and `image_depth`, so the stereo depth can be checked against
it pixel for pixel.

## Extra mono cameras (e.g. the rear camera)

Any other SceneCapture2D can ride the same link as a plain colour camera: add
a second UnrealStereoCam component that streams only that capture — Center =
the capture, CenterCamId = a free id (10 and up), Left / Right blank,
`bStreamCenterDepth` off. The ROS node accepts several streamer connections on
port 3004 at once, and publishes the camera as listed in `extra_cameras`
(`"<cam_id>:<topic>[:<hfov_deg>[:<mask_cam_id>]]"`, rate `extra_cameras_hz`) in
`component_stereo_depth/config/params.yaml`.

**Its own object mask (optional):** a mask capture beside it — the same
`PPM_GroundTruthMask` material, sun-only show flags and manual exposure as the
navcam's mask capture, at the camera's pose and FOV — set as this streamer's
**MaskCaptureName** with a free **MaskCamId**, and that id as the entry's fourth
field. The node then publishes `<topic>/object_mask`, `shadow_mask` and
`shadow_label` (with their mappings), each paired with the image of the same
frame. Terrain Studio sets up the navcam's mask camera only; copy its settings
(a mask capture's render settings live on the placed rover, where Terrain Studio
writes them, and on the Blueprint).

Leo_Raph does this for its rear camera: `RearCam` on the body (behind it,
looking back, pitched -20°, 90° FOV) streamed by `RearCam_Stream` on cam id 10
-> `rear_cam/image_color` (+ `/compressed`, `/camera_info`), shown as REAR on
the dashboard; and `RearCam_Mask` on cam id 13 -> `rear_cam/object_mask`,
`shadow_mask`, `shadow_label`, shown as REAR SEGMENTATION / REAR SHADOW MASK.

## Exposure

By default the captures auto-expose like any Unreal camera. Two optional
controls on the **UnrealStereoCam** component (Details → *StereoCam | Cameras*)
override that — pick **at most one**:

- **Limit Auto Exposure** (`bLimitAutoExposure`) — keeps auto-exposure but clamps
  the EV100 range it may adapt into, via **Min EV100** and **Max EV100**. This is
  the usual fix for the two failure modes on a dim lunar surface: raising
  **Min EV100** stops the shadows being amplified to grey noise; lowering
  **Max EV100** stops bright regolith being blown to white. Set **Min EV100 ==
  Max EV100** to pin a single fixed exposure — identical on both stereo eyes, so
  their brightness matches (mismatched eye exposure poisons stereo matching)
  without turning metering off. These map to the capture's PostProcess
  *Auto Exposure → Min/Max Brightness*, which carry EV100 under UE5's extended
  luminance range.
- **Lock Exposure** (`bLockExposure`) — switches to fully manual metering
  (`AEM_Manual`, no adapting range at all) with **Exposure Compensation EV** as a
  plain brightness dial. Heavier-handed; use it only when you want to remove the
  scene-luminance feedback loop entirely (e.g. a glare study).

Both are off by default — verify the base image looks right before enabling
either. Changing them takes effect at **Play** (they are applied when the
captures are resolved at BeginPlay).
