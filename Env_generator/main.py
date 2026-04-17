"""
Unreal Engine Remote Execution Client
-------------------------------------
This script establishes a network connection to a running instance of Unreal Engine
and triggers the lunar terrain generation pipeline using local data files.
"""

import unreal_api
import time
import os
import sys
import numpy as np
import terrain_files_generator

BASE_DIRECTORY        = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
BASE_MAPS_DIRECTORY   = os.path.join(BASE_DIRECTORY, "maps").replace("\\", "/")
BASE_OUTPUT_DIRECTORY = os.path.join(BASE_DIRECTORY, "outputs").replace("\\", "/")

def generate_lunar_terrain(input_map_filepath, output_map_directory, input_resolution):
    
    # --- 1. Reading Original DEM ---
    raw_elevation_data = terrain_files_generator.terrain_file_reading(input_map_filepath, input_resolution)
    
    # --- 2. Unreal Format Conversion ---
    file_header, unreal_elevation_data = terrain_files_generator.convert_to_unreal_format(
        elevation_data=raw_elevation_data, 
        interpolation_resolution=input_resolution
    )

    # Construct the output filepath based on the source filename
    filename = os.path.basename(input_map_filepath)
    filename_without_extension = os.path.splitext(filename)[0]
    converted_dem_filepath = os.path.join(output_map_directory, f"{filename_without_extension}_converted.txt")
    
    # Export the formatted unreal elevation data
    np.savetxt(
        converted_dem_filepath, 
        unreal_elevation_data, 
        fmt='%s', 
        delimiter=' ', 
        newline='\n', 
        header=file_header, 
        footer='', 
        comments='', 
        encoding=None
    )

    # =========================================================================
    # 3. CALCULATE OPTIMAL LANDSCAPE COMPONENTS
    # =========================================================================
    header_values = [float(val) for val in file_header.split()]
    dem_width, dem_height, interpolation_resolution, z_axis_scale = header_values
    landscape_config = terrain_files_generator.calculate_optimal_landscape_config(dem_width, dem_height)
    
    # FIX: Pass 'base_filename' into the generator so it names the R16 correctly
    terrain_files_generator.create_unreal_heightmap(
        unreal_elevation_data, 
        int(dem_width), 
        int(dem_height), 
        landscape_config, 
        output_map_directory,
        base_filename=filename_without_extension 
    )
    
    # FIX: Construct the final expected heightmap filename to send to Unreal
    heightmap_filename = f"{filename_without_extension}_heightmap.r16"

    # We now return the heightmap_filename as well!
    return landscape_config, interpolation_resolution, z_axis_scale, heightmap_filename


# FIX: Added 'heightmap_filename' to the parameters
def send_to_unreal(landscape_config, interpolation_resolution, z_axis_scale, heightmap_filename):
    """
    Locates a running Unreal Editor instance and executes the terrain 
    generation script with dynamic path resolution.
    """
    
    # --- Remote Connection Setup ---
    remote_exec = unreal_api.RemoteExecution()
    remote_exec.start()
    
    print(f"[*] Searching for Unreal Engine instances... (Root: {BASE_DIRECTORY})")
    time.sleep(2.0) 

    nodes = remote_exec.remote_nodes
    if nodes and len(nodes) > 0:
        first_node = nodes[0]
        node_id = first_node.get("node_id") if isinstance(first_node, dict) else getattr(first_node, "node_id", None)

        if node_id:
            remote_exec.open_command_connection(node_id)
            
            # Construct the absolute path to the dynamically named .r16 file
            target_r16_path = f"{BASE_OUTPUT_DIRECTORY}/{heightmap_filename}"
            
            # --- Command Construction ---
            command = (
                f"import sys; "
                f"sys.path.append('{BASE_DIRECTORY}') if '{BASE_DIRECTORY}' not in sys.path else None; "
                f"import unreal_terrain_generator; "
                f"import importlib; importlib.reload(unreal_terrain_generator); "
                f"unreal_terrain_generator.create_landscape({landscape_config}, {interpolation_resolution}, {z_axis_scale}, '{target_r16_path}')"
            )
            
            remote_exec.run_command(command)
            print(f"[+] Success: Command dispatched to Node [{node_id}]")
    else:
        print("[-] Error: No Unreal instance detected. Ensure 'Remote Execution' is active.")

    remote_exec.stop()


# =========================================================================
# EXECUTION ENTRY POINT - CLI Arguments / Remote Execution Receiver
# =========================================================================
if __name__ == "__main__":
    if not os.path.exists(BASE_OUTPUT_DIRECTORY):
        os.makedirs(BASE_OUTPUT_DIRECTORY)

    input_map_filepath   = os.path.join(BASE_MAPS_DIRECTORY, "Lunar_LROnac_Haworth_1m.tif").replace("\\", "/") 
    output_map_directory = BASE_OUTPUT_DIRECTORY 
    input_resolution     = 1.0

    if len(sys.argv) >= 4:
        input_map_filepath   = sys.argv[1].replace("\\", "/")
        output_map_directory = sys.argv[2].replace("\\", "/")
        input_resolution     = float(sys.argv[3])

    # Execute pipeline
    # 1. Process data locally (Now catches the 4th returned variable: heightmap_filename)
    landscape_config, interpolation_resolution, z_axis_scale, heightmap_filename = generate_lunar_terrain(
        input_map_filepath, 
        output_map_directory, 
        input_resolution
    )
    
    # 2. Send the build command to Unreal (Now passing heightmap_filename)
    send_to_unreal(landscape_config, interpolation_resolution, z_axis_scale, heightmap_filename)