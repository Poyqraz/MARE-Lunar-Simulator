"""
Unreal Engine Landscape Instantiator
------------------------------------
Runs exclusively inside Unreal Engine. Receives processed DEM configuration
from the local Python client and generates the Landscape Actor.
"""

import unreal

CM_PER_METER = 100.0  # Unreal Engine uses Centimeters as its base unit

def create_landscape(landscape_config, interpolation_resolution, z_axis_scale, heightmap_filepath="outputs/lunar_terrain.r16", x_offset=0, y_offset=0, z_offset=0):
    """
    Parses pre-processed DEM data, configures an optimal Unreal Landscape actor, 
    and exports a normalized 16-bit heightmap for manual terrain relief application.
    """
    
    # Unpack the tuple sent by the local execute.py script
    optimal_comp_x, optimal_comp_y, quads, sections, final_width, final_height = landscape_config

    unreal.log(f"[*] Spawning Landscape: {optimal_comp_x}x{optimal_comp_y} components, {quads} quads")

    # Compute physical scale multipliers mapped from standard meters to Unreal centimeters.
    # FIX: Changed 'int()' to 'float()' to prevent rounding errors on resolutions like 0.015
    unreal_map_scale_x = float(CM_PER_METER * abs(interpolation_resolution))
    unreal_map_scale_y = float(CM_PER_METER * abs(interpolation_resolution))

    # =========================================================================
    # 1. INSTANTIATE LANDSCAPE ACTOR IN UNREAL
    # =========================================================================
    # Define the foundational transform for the Landscape actor
    landscape_transform = unreal.Transform(
        location=[x_offset * CM_PER_METER, y_offset * CM_PER_METER, z_offset * CM_PER_METER], 
        rotation=[0.0, 0.0, 0.0], 
        scale=[unreal_map_scale_x, unreal_map_scale_y, z_axis_scale]
    )
    
    # Spawn the procedural landscape framework utilizing the TAPython Landscape API
    landscape_actor = unreal.PythonLandscapeLib.create_landscape(
        landscape_transform, 
        section_size=quads, 
        sections_per_component=sections, 
        component_count_x=optimal_comp_x, 
        component_count_y=optimal_comp_y
    )
    
    # =========================================================================
    # 2. UPDATE VIEWPORT AND EDITOR STATE
    # =========================================================================
    # Update editor selection state and focus the viewport camera on the newly created geometry
    unreal.PythonBPLib.select_actor(landscape_actor, selected=True, notify=True)
    unreal.PythonBPLib.request_viewport_focus_on_selection()
    
    # =========================================================================
    # 3. PROMPT USER WITH IMPORT INSTRUCTIONS
    # =========================================================================
    dialog_title = "Landscape Generation Complete"
    
    # FIX: Injected the heightmap_filepath so the user knows exactly where to look!
    dialog_message = (
        "The Landscape actor has been successfully generated with precise physical scaling.\n\n"
        "To apply the generated heightmap data, please proceed with the following steps:\n\n"
        "1. Enter Landscape Mode (SHIFT + 2).\n"
        "2. Navigate to the 'Manage' tab and ensure the new Landscape is selected.\n"
        "3. Right-click the Landscape in the component list and select 'Import'.\n"
        f"4. Target file:\n   {heightmap_filepath}\n"
        "5. Click 'Import' in the bottom right panel.\n\n"
        "The terrain relief will be applied immediately."
    )
    
    # Suspend Editor execution and visually notify the user of pending manual operations
    unreal.EditorDialog.show_message(
        dialog_title, dialog_message, unreal.AppMsgType.OK, unreal.AppReturnType.OK
    )