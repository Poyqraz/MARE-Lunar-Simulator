import unreal
import os
import struct
import json

# Define the absolute path to the converted DEM (Digital Elevation Model) text file
converted_DEM_interest_zone = os.path.dirname(__file__) + "/DTM_DEM_converted.txt"


def main():
    """Entry point for the script."""
    interest_zone_land, z_scale, w1, h1, x_offset, y_offset = create_landscape(converted_DEM_interest_zone)


def create_landscape(converted_DEM, x_offset=0, y_offset=0, z_offset=0):
    """
    Parses DEM data, configures an Unreal Landscape actor, and exports a 
    normalized 16-bit heightmap for manual importing.
    """

    # =========================================================================
    # 1. PARSE DEM DATA
    # =========================================================================
    with open(converted_DEM) as f:
        # Extract header parameters for landscape spatial configuration
        header = [float(x) for x in next(f).split()]
        w, h, X_geo_offset, Y_geo_offset, interp_resolution, z_scale, z_diff, dem_selected_i, dem_selected_j, X_sampling, Y_sampling = header
        
        # Parse the remaining data into a 2D integer array
        array = [[int(x) for x in line.split()] for line in f]
    
    w = int(w)
    h = int(h) 

    # =========================================================================
    # 2. CALCULATE OPTIMAL LANDSCAPE COMPONENTS
    # =========================================================================
    section_size = 255
    sections_per_component = 2
    selected_count_x = 0
    selected_count_y = 0
    DEM_area = 0
    
    # Iterate to determine the optimal component configuration based on DEM dimensions
    for i in range(1, 50):
        for j in range(1, 50):
            # Compute landscape bounds in vertices
            height_data_size = unreal.PythonLandscapeLib.cal_landscape_size(section_size, sections_per_component=2, component_count_x=i, component_count_y=j)
            h_predicted = height_data_size[1]
            w_predicted = height_data_size[0]
            DEM_area_new = h_predicted * w_predicted
            
            # Update component counts if the predicted area is valid and maximizes coverage
            if (h_predicted <= h and w_predicted <= w and DEM_area_new > DEM_area):
                DEM_area = DEM_area_new
                selected_count_x = i
                selected_count_y = j

    # Compute terrain scale factors based on the interpolation resolution
    unreal_map_X_scale = int(100 * abs(interp_resolution))
    unreal_map_Y_scale = int(100 * abs(interp_resolution))

    # =========================================================================
    # 3. INSTANTIATE LANDSCAPE ACTOR
    # =========================================================================
    # Define spatial transform for the Landscape actor
    t = unreal.Transform(
        location=[x_offset * 100, y_offset * 100, z_offset * 100], 
        rotation=[0, 0, 0], 
        scale=[unreal_map_X_scale, unreal_map_Y_scale, z_scale]
    )
    
    # Spawn the Landscape actor using the TAPython library
    this_land = unreal.PythonLandscapeLib.create_landscape(
        t, 
        section_size=section_size, 
        sections_per_component=2, 
        component_count_x=selected_count_x, 
        component_count_y=selected_count_y
    )
    
    final_size = unreal.PythonLandscapeLib.cal_landscape_size(
        section_size, 
        sections_per_component=2, 
        component_count_x=selected_count_x, 
        component_count_y=selected_count_y
    )
    x_count, y_count = final_size[0], final_size[1]

    # =========================================================================
    # 4. NORMALIZE ELEVATION DATA TO 16-BIT
    # =========================================================================
    unreal.log("Processing and normalizing elevation data to 16-bit format...")
    
    # Flatten array to extract global minimum and maximum elevation values
    flat_array = [item for sublist in array for item in sublist]
    min_dem = min(flat_array)
    max_dem = max(flat_array)
    range_dem = max(1, max_dem - min_dem)
    
    max_x_index = len(array[0]) - 1
    max_y_index = len(array) - 1

    # Initialize a contiguous 1D list for the heightmap data
    python_list = [0] * (x_count * y_count)

    # Process and normalize each vertex
    for y in range(y_count):
        for x in range(x_count):
            index = x + y * x_count
            
            # Clamp coordinates to prevent out-of-bounds indexing
            clamp_x = min(x, max_x_index)
            clamp_y = min(y, max_y_index)
            v = array[clamp_y][clamp_x]

            # Map the elevation value to Unreal's 16-bit range (0 to 65535)
            normalized_v = ((v - min_dem) / range_dem) * 65535
            python_list[index] = max(0, min(int(normalized_v), 65535))

    # =========================================================================
    # 5. EXPORT NATIVE .R16 HEIGHTMAP AND METADATA
    # =========================================================================
    project_dir = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
    
    # Target the .r16 extension to ensure Unreal identifies the file as a 16-bit heightmap
    raw_path = os.path.join(project_dir, "lunar_terrain.r16").replace("\\", "/")
    json_path = os.path.join(project_dir, "lunar_terrain.json").replace("\\", "/")
    
    # Remove existing files to prevent partial overwrites or file locks
    for path in [raw_path, json_path]:
        if os.path.exists(path):
            try: 
                os.remove(path)
            except OSError: 
                pass
    
    # Write the R16 binary data in chunks to prevent MemoryError exceptions
    unreal.log(f"Writing {len(python_list)} data points to the R16 file...")
    try:
        with open(raw_path, "wb") as f:
            chunk_size = 100000  # Process data in 100,000-point chunks
            for i in range(0, len(python_list), chunk_size):
                chunk = python_list[i : i + chunk_size]
                # Pack and write the current chunk in Little Endian 16-bit format ('<H')
                f.write(struct.pack(f'<{len(chunk)}H', *chunk))
            
            # Force the OS buffer to write to disk immediately
            f.flush()
            os.fsync(f.fileno())
        
        peso_mb = os.path.getsize(raw_path) / (1024 * 1024)
        unreal.log(f"SUCCESS: R16 file generated successfully. Size: {peso_mb:.2f} MB")
        
    except Exception as e:
        unreal.log_error(f"Critical failure while writing the R16 file: {e}")
        
    # Generate JSON metadata for automatic dimension resolution during import
    with open(json_path, "w") as f:
        json.dump({"width": x_count, "height": y_count, "bpp": 16}, f)

    # =========================================================================
    # 6. UPDATE VIEWPORT AND EDITOR STATE
    # =========================================================================
    # Select the newly created actor and shift camera focus to its bounds
    unreal.PythonBPLib.select_actor(this_land, selected=True, notify=True)
    unreal.PythonBPLib.request_viewport_focus_on_selection()
    
    # =========================================================================
    # 7. PROMPT USER WITH IMPORT INSTRUCTIONS (UI POP-UP)
    # =========================================================================
    dialog_title = "Landscape Generation Complete"
    dialog_message = (
        "The Landscape actor and corresponding R16 heightmap have been successfully generated with precise scaling.\n\n"
        "To apply the heightmap data, please proceed with the following steps:\n\n"
        "1. Enter Landscape Mode (SHIFT + 2).\n"
        "2. Navigate to the 'Manage' tab and ensure the new Landscape is selected.\n"
        "3. Right-click the Landscape in the component list and select 'Import'.\n"
        f"4. Target file:\n   {raw_path}\n"
        "5. Click 'Import' in the bottom right panel.\n\n"
        "The terrain relief will be applied immediately."
    )
    
    # Invoke modal dialog to notify the user of pending manual steps
    unreal.EditorDialog.show_message(
        dialog_title, 
        dialog_message, 
        unreal.AppMsgType.OK, 
        unreal.AppReturnType.OK
    )
        
    return this_land, z_scale, w, h, X_geo_offset, Y_geo_offset


if __name__ == "__main__":
    main()