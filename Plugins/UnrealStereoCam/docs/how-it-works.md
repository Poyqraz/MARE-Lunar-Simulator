# How UnrealStereoCam works

This component streams the navcams to ROS without stalling the game:
SceneCaptures render on the render thread **only when a frame is sent**
(`SendHz`, with `bCaptureOnDemand`, the default), readback is **asynchronous**
(polled, never flushed mid-render), and a worker thread ships completed frames
over TCP. The game thread only queues the renders and copies.

Rendering on demand doubled the editor's frame rate (6.7 -> 14.2 frames/s with
all camera outputs read) with identical images: each capture is a full scene
render, and rendering every engine frame threw most of them away. The captures
keep their rendering state between renders (exposure, temporal AA, Lumen). The
ground-truth depth capture also skips all shading (lighting, shadows, GI,
reflections, decals, post-processing). Untick `bCaptureOnDemand` to render
every frame as before.

On the ROS side, `component_stereo_depth` listens on port 3004 and pairs
left/right frames by frame id: every capture enqueued in one tick carries the
same `GFrameCounter`, so a pair always shows the same world state.
