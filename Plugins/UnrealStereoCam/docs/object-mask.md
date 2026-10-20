# Object segmentation mask

An object mask, each object a flat colour, made by reading Unreal's
**Custom Depth-Stencil** buffer and colouring it in a post-process material. It streams as a fourth capture on the same path as
the RGB cameras.

1. **Enable the buffer.** Project Settings → Rendering → Postprocessing →
   **Custom Depth-Stencil Pass = `Enabled with Stencil`**, then restart the
   editor.

2. **Tag every actor you want segmented — this is the required per-object step.**
   On each mesh: *Details → Rendering →* set **Render CustomDepth Pass = true**
   **and give it a nonzero CustomDepth Stencil Value (an id, 1–255)**. Same id →
   same colour (e.g. all boulders share one id); unique ids → per-object masks.
   Id 0 is "untagged" and renders black. Special cases:
   - **Nanite meshes** (typical for Megascans rocks/terrain) also need Nanite's
     custom-depth path on, or they silently ignore the stencil value: add
     ```ini
     [SystemSettings]
     r.Nanite.CustomDepth=1
     ```
     to `Config/DefaultEngine.ini`.
   - **Landscape:** set the same two properties on the Landscape actor — and on
     **each** `LandscapeStreamingProxy` if World Partition split the terrain.
   - **Painted foliage:** set them on the **Foliage Type asset**, not on the
     placed instances.

3. **Colouriser material `PPM_GroundTruthMask`** (in `/Game/GroundTruth_Masks/Mask`,
   where Terrain Studio looks for it). A Material with *Material Domain =
   Post Process*, *Blendable Location = After Tonemapping*, that reads a
   `SceneTexture: CustomStencil` node (R channel) and maps the value to a flat
   colour into **Emissive Color** (e.g. a `Custom` HLSL node hashing the id to
   RGB, black when the value is 0).

4. **Mask capture.** A fourth `SceneCaptureComponent2D` (e.g. **`Navcam_Mask`**),
   posed and FOV-matched to `NavcamCenter`, with `PPM_GroundTruthMask` added to its
   *Post Process Settings → Post Process Materials* (weight 1). Leave its render
   target empty (auto-created). On the **UnrealStereoCam** component set
   **MaskCaptureName** to it; its **MaskCamId** (default 3, under *Advanced*)
   must equal `mask_camera_id` in the stereo node's params.

5. **Name the ids (what each number means).** The mask image carries only
   colours, so the classes (id, name, colour, group) are listed in
   `component_stereo_depth/config/mask_classes.json` — the same file as Terrain
   Studio's `config/mask_classes.json`, which sets the CustomDepth Stencil Values
   of step 2 and the mask colours. **Edit both copies together**; Terrain
   Studio's ground-truth page says when they differ. The stereo node republishes
   it as JSON on `navcam/central/object_mask_mapping` (id → name, e.g.
   `{"1": "sky", "5": "landscape", "9": "boulder"}`) and
   `navcam/central/object_mask_classes` (with colours and groups).
