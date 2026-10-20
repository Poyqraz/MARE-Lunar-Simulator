# How UnrealEventCam works

Renders an intensity image with each game frame, generates brightness-change
**events** from it with the ESIM model, and streams them to a ROS node over TCP.
Same no-stall design as the sibling `UnrealStereoCam` plugin: the SceneCapture
renders on the render thread, the readback is asynchronous, and a worker thread
runs the event model and drains to the socket. The game thread never blocks.

## How an event camera works (and the one caveat here)

A DVS pixel fires an **event** `(x, y, t, polarity)` whenever the log intensity
at that pixel has changed by a contrast threshold `C` since it last fired —
positive polarity for a brightness increase, negative for a decrease. There is
no frame: the output is a sparse, asynchronous, microsecond-timestamped stream.

ESIM reconstructs this from rendered frames by looking at how far the log
intensity moved between two consecutive frames and emitting one event per
threshold crossing, with the crossing time interpolated linearly across the
frame interval.

**Caveat — sampling rate.** This is only accurate when frames are rendered far
faster than the scene changes. Here the sampling rate *is* the render frame
rate, so fast motion between frames is linearly interpolated and can alias, and
undersampling *loses* events (unlike an RGB stream, where it just drops frames).
For the cleanest stream: run the editor at a high, steady FPS, keep the event
resolution modest, and avoid extremely small contrast thresholds.

## Acknowledgments

The event-generation core (`EventSimulator.h` / `.cpp`) is a port of the
**EventSimulator** from **ESIM (rpg_esim)** by the Robotics and Perception Group,
University of Zurich — used under MIT License (see [`LICENSE`](../LICENSE)).

The port keeps ESIM's algorithm — per-pixel log-intensity threshold crossings,
linear timestamp interpolation between frames, per-polarity contrast thresholds,
optional Gaussian threshold noise and a per-pixel refractory period — and only
swaps the OpenCV / glog / ze types for Unreal primitives so it has no external
dependencies.

Upstream: https://github.com/uzh-rpg/rpg_esim
