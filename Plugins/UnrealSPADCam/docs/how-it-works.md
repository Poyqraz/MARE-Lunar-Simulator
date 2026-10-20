# How UnrealSPADCam works

Renders an intensity image with each game frame and streams it to a ROS node
over TCP, where the **spadSim** photon model turns it into single-photon binary
frames. Same no-stall design as the sibling `UnrealEventCam` / `UnrealStereoCam`
plugins: the SceneCapture renders on the render thread, the readback is
asynchronous, and a worker thread converts to 8-bit grayscale and drains to the
socket. The game thread never blocks.

## Where the model lives

This plugin is **only the front-end** — it delivers intensity frames. The SPAD
sensor model (photon-flux estimation, Poisson photon arrivals, binary
thresholding, digitisation) runs in the ROS component **`component_spad_camera`**,
which ports **spadSim** by David Rodriguez-Martinez (MIT). That split keeps the
physics in Python/numpy — exactly spadSim's implementation — and matches how the
stereo pipeline works (plugin streams pixels, ROS does the processing).

> Upstream model: https://github.com/drodriguezSRL/spadSim (MIT, © 2025 David
> Rodriguez-Martinez). Related: *"Fast Vision in the Dark: A Case for
> Single-Photon Imaging in Planetary Navigation"*, arXiv:2510.10597.

## What a SPAD camera is

A Single-Photon Avalanche Diode pixel fires when it detects **one photon**. In a
very short exposure a SPAD produces a **binary** frame — 1 where a photon was
detected, 0 elsewhere — governed by Poisson photon statistics. Summing many
binary frames reconstructs a grayscale image, which is what makes SPADs strong in
extreme low light (relevant to lunar permanently-shadowed regions). The ROS node
does the photon sampling and the reconstruction; this plugin feeds it the scene.
