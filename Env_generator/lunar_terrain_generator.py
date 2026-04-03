import unreal
import os
import json
import numpy as np
import math
import sys

# =============================================================================
# Global Configuration & Environment Constraints
# =============================================================================
BASE_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
DEBUG_MODE = True

# Unreal Engine specific landscape constants
UNREAL_SEA_LEVEL = 32767
UNREAL_Z_SCALE_DIVISOR = 256.0
MAX_COMPONENT_GRID_SIZE = 50
UINT16_MAX = 65535
CM_PER_METER = 100.0


def main(input_filepath, spatial_resolution):
    """
    Primary execution block for the DEM conversion and Landscape generation pipeline.
    Coordinates data ingestion, format conversion, and actor instantiation.
    """
    
    # Isolate the file extension to dynamically route the data ingestion
    _, file_extension = os.path.splitext(input_filepath)
    file_extension = file_extension.lower()
    
    unreal.log(f"Initializing DEM ingestion for file: {input_filepath} at {spatial_resolution} resolution")
    
    # Route to the appropriate NumPy I/O function based on the detected extension
    if file_extension == '.npy':
        raw_elevation_data = np.load(input_filepath)
    elif file_extension in ['.csv', '.txt']:
        # Fallback to standard text parsing for human-readable datasets
        # Note: Delimiter is set to comma. If using space-separated .txt files, change delimiter to " "
        raw_elevation_data = np.loadtxt(input_filepath, delimiter=",", skiprows=0)
    else:
        unreal.log_error(f"Process Terminated: Unsupported file extension '{file_extension}'. Must be .npy, .csv, or .txt.")
        return
    
    # Process the raw array into an Unreal-compatible format
    converted_dem_filepath = convert_to_unreal_format(
        elevation_data=raw_elevation_data, 
        input_filepath=input_filepath, 
        output_directory=BASE_DIRECTORY, 
        interpolation_resolution=spatial_resolution
    )

    print(f"Conversion complete. Unreal-formatted DEM saved to: {converted_dem_filepath}\n")
    
    # Instantiate the landscape actor in the current Unreal Engine level
    landscape_actor, z_axis_scale, dem_width, dem_height = create_landscape(converted_dem_filepath)


def create_landscape(converted_dem_filepath, x_offset=0, y_offset=0, z_offset=0):
    """
    Parses pre-processed DEM data, configures an optimal Unreal Landscape actor, 
    and exports a normalized 16-bit heightmap for manual terrain generation.
    """

    # =========================================================================
    # 1. PARSE PRE-PROCESSED DEM DATA
    # =========================================================================
    with open(converted_dem_filepath, 'r') as text_file:
        # Extract spatial configuration parameters from the file header
        header_values = [float(val) for val in text_file.readline().split()]
        dem_width, dem_height, interpolation_resolution, z_axis_scale = header_values
    
    dem_width = int(dem_width)
    dem_height = int(dem_height) 

    # Ingest the matrix data into a NumPy array, omitting the header line
    elevation_grid = np.loadtxt(converted_dem_filepath, skiprows=1, dtype=np.float32)

    # =========================================================================
    # 2. CALCULATE OPTIMAL LANDSCAPE COMPONENTS
    # =========================================================================
    config = calculate_optimal_landscape_config(dem_width, dem_height)
    if not config:
        return None
        
    optimal_comp_x, optimal_comp_y, quads, sections, final_width, final_height = config

    if DEBUG_MODE:
        unreal.log(f"Optimal Setup Found: {quads} Quads, {sections} Sections.")
        unreal.log(f"Component Layout: {optimal_comp_x}x by {optimal_comp_y}y")
        unreal.log(f"Final Vertices: {final_width}x by {final_height}y (DEM bounds: {dem_width}x by {dem_height}y)")

    # Compute physical scale multipliers derived from the spatial resolution
    unreal_map_scale_x = int(CM_PER_METER * abs(interpolation_resolution))
    unreal_map_scale_y = int(CM_PER_METER * abs(interpolation_resolution))

    # =========================================================================
    # 3. INSTANTIATE LANDSCAPE ACTOR IN UNREAL
    # =========================================================================
    # Define the foundational transform for the Landscape actor
    landscape_transform = unreal.Transform(
        location=[x_offset * CM_PER_METER, y_offset * CM_PER_METER, z_offset * CM_PER_METER], 
        rotation=[0.0, 0.0, 0.0], 
        scale=[unreal_map_scale_x, unreal_map_scale_y, z_axis_scale]
    )
    
    # Spawn the procedural landscape utilizing the TAPython Landscape API
    landscape_actor = unreal.PythonLandscapeLib.create_landscape(
        landscape_transform, 
        section_size=quads, 
        sections_per_component=sections, 
        component_count_x=optimal_comp_x, 
        component_count_y=optimal_comp_y
    )
    
    # =========================================================================
    # 4. NORMALIZE ELEVATION DATA TO 16-BIT 
    # =========================================================================
    unreal.log("Processing and normalizing elevation data to 16-bit format...")
    
    min_elevation = np.min(elevation_grid)
    max_elevation = np.max(elevation_grid)
    elevation_range = max(1.0, max_elevation - min_elevation)

    # Apply edge padding to the array to align with the final landscape bounds, 
    # mitigating edge artifacts and matching Unreal's vertex requirements
    pad_y = max(0, final_height - dem_height)
    pad_x = max(0, final_width - dem_width)
    padded_grid = np.pad(elevation_grid, ((0, pad_y), (0, pad_x)), mode='edge')

    # Execute vectorized normalization across the entire grid to map values 
    # strictly within the Unreal 16-bit grayscale spectrum (0 to 65535)
    normalized_grid = ((padded_grid - min_elevation) / elevation_range) * UINT16_MAX
    
    # Cast the normalized float array to a 16-bit unsigned integer format natively
    heightmap_data = np.clip(normalized_grid, 0, UINT16_MAX).astype(np.uint16)

    # =========================================================================
    # 5. EXPORT NATIVE .R16 HEIGHTMAP AND METADATA
    # =========================================================================
    project_directory = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
    heightmap_filepath = os.path.join(project_directory, "lunar_terrain.r16").replace("\\", "/")
    metadata_filepath = os.path.join(project_directory, "lunar_terrain.json").replace("\\", "/")
    
    # Purge existing files to prevent partial overwrites or locking exceptions
    for file_path in [heightmap_filepath, metadata_filepath]:
        if os.path.exists(file_path):
            try: os.remove(file_path)
            except OSError: pass
    
    unreal.log(f"Writing {heightmap_data.size} data points to the R16 file...")
    
    try:
        # Export the 16-bit array to a binary file via direct memory dump 
        # for optimized I/O performance
        with open(heightmap_filepath, "wb") as binary_file:
            heightmap_data.tofile(binary_file) 
            
            # Force the OS buffer to flush to disk to ensure data integrity
            binary_file.flush()
            os.fsync(binary_file.fileno())
        
        file_size_mb = os.path.getsize(heightmap_filepath) / (1024 * 1024)
        unreal.log(f"SUCCESS: R16 file generated successfully. Size: {file_size_mb:.2f} MB")
        
    except Exception as e:
        unreal.log_error(f"Critical I/O failure while writing the R16 file: {e}")
        
    # Generate JSON metadata to assist with automated dimension resolution during Editor import
    with open(metadata_filepath, "w") as json_file:
        json.dump({"width": final_width, "height": final_height, "bpp": 16}, json_file)

    # =========================================================================
    # 6. UPDATE VIEWPORT AND EDITOR STATE
    # =========================================================================
    # Update editor selection state and focus the viewport camera on the new geometry
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
    
    # Suspend Editor execution and notify the user of pending manual operations
    unreal.EditorDialog.show_message(
        dialog_title, dialog_message, unreal.AppMsgType.OK, unreal.AppReturnType.OK
    )
        
    return landscape_actor, z_axis_scale, dem_width, dem_height


def convert_to_unreal_format(elevation_data, input_filepath, output_directory, interpolation_resolution=1.0):
    """
    Transforms and scales a raw Digital Elevation Model (DEM) array to conform 
    to Unreal Engine's standard landscape specifications and sea-level offsets.
    """
    # Sanitize zero-values to prevent skewing the global height scale minimums
    elevation_data[elevation_data == 0] = np.nan
    
    # Convert metric elevation data to centimeters (Unreal standard units)
    elevation_cm = elevation_data * CM_PER_METER

    # Calculate the maximum elevation ceiling, executing safely against NaNs
    max_elevation_cm = np.nanmax(elevation_cm)
    if max_elevation_cm == 0 or np.isnan(max_elevation_cm): 
        max_elevation_cm = 1.0 

    # Derive Unreal Engine scaling parameters
    z_axis_scale = max_elevation_cm / UNREAL_Z_SCALE_DIVISOR
    height_scaling_factor = UNREAL_SEA_LEVEL / max_elevation_cm   
    
    # Execute primary scaling transformation against the Unreal 16-bit midpoint
    scaled_elevation = (elevation_cm * height_scaling_factor) + UNREAL_SEA_LEVEL
    
    # Replace anomalous data ('No Data' NaNs and infinities) with the standard Unreal sea level baseline
    sanitized_elevation = np.nan_to_num(
        scaled_elevation, 
        nan=UNREAL_SEA_LEVEL, 
        posinf=UNREAL_SEA_LEVEL, 
        neginf=UNREAL_SEA_LEVEL
    )
    
    # Cast the finalized float data to integers to satisfy Unreal landscape import protocols
    unreal_elevation_data = np.floor(sanitized_elevation).astype(int)

    # Formulate the spatial resolution header
    file_header = f"{elevation_data.shape[1]} {elevation_data.shape[0]} {interpolation_resolution} {z_axis_scale}"

    # Construct the output filepath based on the source filename
    filename = os.path.basename(input_filepath)
    filename_without_extension = os.path.splitext(filename)[0]
    output_filepath = os.path.join(output_directory, f"{filename_without_extension}_converted.txt")
    
    # Export the formatted payload to a serialized text file for intermediate caching
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


def calculate_optimal_landscape_config(dem_width, dem_height):
    """
    Analyzes DEM dimensions to iteratively compute the most memory-efficient 
    Unreal Engine landscape configuration that fully encompasses the designated bounds.
    """
    # Valid architectural bounds for Unreal Engine Landscapes
    VALID_QUADS = [63, 127, 255]
    VALID_SECTIONS = [1, 2]
    
    best_area = float('inf')
    best_config = None

    # Evaluate all valid permutations of Quads and Sections
    for quads in VALID_QUADS:
        for sections in VALID_SECTIONS:
            vertices_per_comp = quads * sections
            
            # Apply ceiling division to ensure the generated component grid fully encompasses the DEM
            comp_x = math.ceil((dem_width - 1) / vertices_per_comp)
            comp_y = math.ceil((dem_height - 1) / vertices_per_comp)
            
            # Bypass configurations exceeding the maximum component threshold to maintain Editor performance
            if comp_x > MAX_COMPONENT_GRID_SIZE or comp_y > MAX_COMPONENT_GRID_SIZE:
                continue
                
            predicted_width = (comp_x * vertices_per_comp) + 1
            predicted_height = (comp_y * vertices_per_comp) + 1
            predicted_area = predicted_width * predicted_height
            
            # Update the optimal configuration if the current iteration yields a smaller total area footprint
            if predicted_area < best_area:
                best_area = predicted_area
                best_config = (comp_x, comp_y, quads, sections, predicted_width, predicted_height)

    # Halt execution if the DEM dimensions drastically exceed standard landscape capability
    if not best_config:
        unreal.log_error("DEM dimensions exceed the maximum 50x50 component threshold. Consider world partitioning or map splitting.")
        return None
        
    return best_config

# =========================================================================
# EXECUTION ENTRY POINT - Handles inputs from Unreal UI
# =========================================================================
if __name__ == "__main__":
    # Default fallbacks in case the script is run directly without UI arguments
    target_filepath = os.path.join(BASE_DIRECTORY, "lunalab.npy")
    target_resolution = 0.01

    # If arguments are passed via Unreal's "Execute Python Command" node
    if len(sys.argv) >= 3:
        target_filepath = sys.argv[1]
        try:
            target_resolution = float(sys.argv[2])
        except ValueError:
            unreal.log_error(f"Invalid spatial resolution '{sys.argv[2]}' passed. Defaulting to 0.01.")
            target_resolution = 0.01

    # Execute the main function with the gathered parameters
    main(target_filepath, target_resolution)