import unreal
import os
import json
import numpy as np

# Configuration constraints
BASE_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
INPUT_DEM_FILEPATH = os.path.join(BASE_DIRECTORY, "DEM_interest_zone.csv")
DEBUG_MODE = True

# Unreal Engine & Landscape Specific Constants
UNREAL_SEA_LEVEL = 32767
UNREAL_Z_SCALE_DIVISOR = 256.0
UNREAL_QUADS_PER_SECTION = 255
UNREAL_SECTIONS_PER_COMPONENT = 2
MAX_COMPONENT_GRID_SIZE = 50
UINT16_MAX = 65535
CM_PER_METER = 100.0


def main():
    """Primary execution block for the DEM conversion and Landscape generation process."""
    spatial_resolution = 1.0
    
    # Load the initial elevation data from the CSV file
    raw_elevation_data = np.loadtxt(INPUT_DEM_FILEPATH, delimiter=",", skiprows=0)
    
    converted_dem_filepath = convert_to_unreal_format(
        elevation_data=raw_elevation_data, 
        input_filepath=INPUT_DEM_FILEPATH, 
        output_directory=BASE_DIRECTORY, 
        interpolation_resolution=spatial_resolution
    )

    print(f"Conversion complete. Unreal-formatted DEM saved to: {converted_dem_filepath}\n")
    
    # Generate the landscape in Unreal Engine using the processed DEM
    landscape_actor, z_axis_scale, dem_width, dem_height = create_landscape(converted_dem_filepath)


def create_landscape(converted_dem_filepath, x_offset=0, y_offset=0, z_offset=0):
    """
    Parses DEM data, configures an Unreal Landscape actor, and exports a 
    normalized 16-bit heightmap for manual importing.
    """

    # =========================================================================
    # 1. PARSE PRE-PROCESSED DEM DATA (OPTIMIZED)
    # =========================================================================
    with open(converted_dem_filepath, 'r') as text_file:
        # Extract header parameters needed for landscape spatial configuration
        header_values = [float(val) for val in text_file.readline().split()]
        dem_width, dem_height, interpolation_resolution, z_axis_scale = header_values
    
    dem_width = int(dem_width)
    dem_height = int(dem_height) 

    # Use NumPy to load the remaining grid instantly, skipping the header line
    elevation_grid = np.loadtxt(converted_dem_filepath, skiprows=1, dtype=np.float32)

    # =========================================================================
    # 2. CALCULATE OPTIMAL LANDSCAPE COMPONENTS
    # =========================================================================
    optimal_component_count_x = 0
    optimal_component_count_y = 0
    max_covered_area = 0
    
    # Iterate through possible component grid configurations
    for comp_x in range(1, MAX_COMPONENT_GRID_SIZE):
        for comp_y in range(1, MAX_COMPONENT_GRID_SIZE):
            predicted_dimensions = unreal.PythonLandscapeLib.cal_landscape_size(
                UNREAL_QUADS_PER_SECTION, 
                sections_per_component=UNREAL_SECTIONS_PER_COMPONENT, 
                component_count_x=comp_x, 
                component_count_y=comp_y
            )
            
            predicted_width = predicted_dimensions[0]
            predicted_height = predicted_dimensions[1]
            predicted_area = predicted_width * predicted_height
            
            if (predicted_height <= dem_height and predicted_width <= dem_width and predicted_area > max_covered_area):
                max_covered_area = predicted_area
                optimal_component_count_x = comp_x
                optimal_component_count_y = comp_y

    if DEBUG_MODE:
        unreal.log(f"Optimal Component Layout: {optimal_component_count_x}x by {optimal_component_count_y}y")

    unreal_map_scale_x = int(CM_PER_METER * abs(interpolation_resolution))
    unreal_map_scale_y = int(CM_PER_METER * abs(interpolation_resolution))

    # =========================================================================
    # 3. INSTANTIATE LANDSCAPE ACTOR IN UNREAL
    # =========================================================================
    landscape_transform = unreal.Transform(
        location=[x_offset * CM_PER_METER, y_offset * CM_PER_METER, z_offset * CM_PER_METER], 
        rotation=[0.0, 0.0, 0.0], 
        scale=[unreal_map_scale_x, unreal_map_scale_y, z_axis_scale]
    )
    
    landscape_actor = unreal.PythonLandscapeLib.create_landscape(
        landscape_transform, 
        section_size=UNREAL_QUADS_PER_SECTION, 
        sections_per_component=UNREAL_SECTIONS_PER_COMPONENT, 
        component_count_x=optimal_component_count_x, 
        component_count_y=optimal_component_count_y
    )
    
    final_landscape_size = unreal.PythonLandscapeLib.cal_landscape_size(
        UNREAL_QUADS_PER_SECTION, 
        sections_per_component=UNREAL_SECTIONS_PER_COMPONENT, 
        component_count_x=optimal_component_count_x, 
        component_count_y=optimal_component_count_y
    )
    final_width = final_landscape_size[0]
    final_height = final_landscape_size[1]

    # =========================================================================
    # 4. NORMALIZE ELEVATION DATA TO 16-BIT (NUMPY VECTORIZED)
    # =========================================================================
    unreal.log("Processing and normalizing elevation data to 16-bit format...")
    
    min_elevation = np.min(elevation_grid)
    max_elevation = np.max(elevation_grid)
    elevation_range = max(1.0, max_elevation - min_elevation)

    # Pad the array to match the final landscape dimensions by repeating the edge pixels
    pad_y = max(0, final_height - dem_height)
    pad_x = max(0, final_width - dem_width)
    padded_grid = np.pad(elevation_grid, ((0, pad_y), (0, pad_x)), mode='edge')

    # Vectorized normalization across the entire grid simultaneously
    normalized_grid = ((padded_grid - min_elevation) / elevation_range) * UINT16_MAX
    
    # Cast to final 16-bit unsigned integer format natively
    heightmap_data = np.clip(normalized_grid, 0, UINT16_MAX).astype(np.uint16)

    # =========================================================================
    # 5. EXPORT NATIVE .R16 HEIGHTMAP AND METADATA
    # =========================================================================
    project_directory = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
    heightmap_filepath = os.path.join(project_directory, "lunar_terrain.r16").replace("\\", "/")
    metadata_filepath = os.path.join(project_directory, "lunar_terrain.json").replace("\\", "/")
    
    for file_path in [heightmap_filepath, metadata_filepath]:
        if os.path.exists(file_path):
            try: os.remove(file_path)
            except OSError: pass
    
    unreal.log(f"Writing {heightmap_data.size} data points to the R16 file...")
    
    # NumPy arrays can be dumped directly to binary files incredibly fast
    try:
        with open(heightmap_filepath, "wb") as binary_file:
            # Writes the raw 16-bit C-array bytes directly to disk
            heightmap_data.tofile(binary_file) 
            
            binary_file.flush()
            os.fsync(binary_file.fileno())
        
        file_size_mb = os.path.getsize(heightmap_filepath) / (1024 * 1024)
        unreal.log(f"SUCCESS: R16 file generated successfully. Size: {file_size_mb:.2f} MB")
        
    except Exception as e:
        unreal.log_error(f"Critical failure while writing the R16 file: {e}")
        
    with open(metadata_filepath, "w") as json_file:
        json.dump({"width": final_width, "height": final_height, "bpp": 16}, json_file)

    # =========================================================================
    # 6. UPDATE VIEWPORT AND EDITOR STATE
    # =========================================================================
    unreal.PythonBPLib.select_actor(landscape_actor, selected=True, notify=True)
    unreal.PythonBPLib.request_viewport_focus_on_selection()
    
    # =========================================================================
    # 7. PROMPT USER WITH IMPORT INSTRUCTIONS
    # =========================================================================
    dialog_title = "Landscape Generation Complete"
    dialog_message = (
        "The Landscape actor and corresponding R16 heightmap have been successfully generated with precise scaling.\n\n"
        "To apply the heightmap data, please proceed with the following steps:\n\n"
        "1. Enter Landscape Mode (SHIFT + 2).\n"
        "2. Navigate to the 'Manage' tab and ensure the new Landscape is selected.\n"
        "3. Right-click the Landscape in the component list and select 'Import'.\n"
        f"4. Target file:\n   {heightmap_filepath}\n"
        "5. Click 'Import' in the bottom right panel.\n\n"
        "The terrain relief will be applied immediately."
    )
    
    unreal.EditorDialog.show_message(
        dialog_title, dialog_message, unreal.AppMsgType.OK, unreal.AppReturnType.OK
    )
        
    return landscape_actor, z_axis_scale, dem_width, dem_height


def convert_to_unreal_format(elevation_data, input_filepath, output_directory, interpolation_resolution=1.0):
    """Processes and scales a Digital Elevation Model (DEM) array to match Unreal Engine specifications."""
    elevation_data[elevation_data == 0] = np.nan
    elevation_cm = elevation_data * CM_PER_METER

    max_elevation_cm = np.nanmax(elevation_cm)
    if max_elevation_cm == 0 or np.isnan(max_elevation_cm): 
        max_elevation_cm = 1.0 

    z_axis_scale = max_elevation_cm / UNREAL_Z_SCALE_DIVISOR
    height_scaling_factor = UNREAL_SEA_LEVEL / max_elevation_cm   
    
    scaled_elevation = (elevation_cm * height_scaling_factor) + UNREAL_SEA_LEVEL
    
    sanitized_elevation = np.nan_to_num(
        scaled_elevation, 
        nan=UNREAL_SEA_LEVEL, 
        posinf=UNREAL_SEA_LEVEL, 
        neginf=UNREAL_SEA_LEVEL
    )
    
    unreal_elevation_data = np.floor(sanitized_elevation).astype(int)

    file_header = f"{elevation_data.shape[1]} {elevation_data.shape[0]} {interpolation_resolution} {z_axis_scale}"

    filename = os.path.basename(input_filepath)
    filename_without_extension = os.path.splitext(filename)[0]
    output_filepath = os.path.join(output_directory, f"{filename_without_extension}_converted.txt")
    
    np.savetxt(
        output_filepath, 
        unreal_elevation_data, 
        fmt='%s', 
        delimiter=' ', 
        newline='\n', 
        header=file_header, 
        footer='', 
        comments='', 
        encoding=None
    )
    
    return output_filepath

if __name__ == "__main__":
    main()