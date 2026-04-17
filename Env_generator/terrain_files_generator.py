import os
import numpy as np
import math
import json

# --- Optional Dependency: tifffile ---
# We attempt to import tifffile for GeoTIFF support. If it is missing from the 
# Unreal Python environment, we log a warning but allow the script to continue 
# for standard array formats (.npy, .csv).
try:
    import tifffile
    TIFFFILE_AVAILABLE = True
except ImportError:
    TIFFFILE_AVAILABLE = False
    print("[-] 'tifffile' not found. Processing .tif files will not be supported.")


# Unreal Engine specific landscape constants
UNREAL_SEA_LEVEL = 32767             # 16-bit midpoint (0-65535) used as Z-axis zero
UNREAL_Z_SCALE_DIVISOR = 256.0       # Engine-hardcoded divisor for Z-scale calculations
MAX_COMPONENT_GRID_SIZE = 50         # Max recommended components to prevent Editor freezing
UINT16_MAX = 65535                   # Maximum value for 16-bit unsigned integer
CM_PER_METER = 100.0                 # Unreal Engine uses Centimeters as its base unit


def terrain_file_reading(input_filepath, spatial_resolution):
    # Isolate the file extension to dynamically route the data ingestion
    _, file_extension = os.path.splitext(input_filepath)
    file_extension = file_extension.lower()
    
    print(f"[*] Initializing DEM ingestion for file: {input_filepath}")
    
    # --- 1. Data Ingestion Routing ---
    if file_extension == '.npy':
        raw_elevation_data = np.load(input_filepath)
        
    elif file_extension in ['.csv', '.txt']:
        # Fallback to standard text parsing for human-readable datasets
        raw_elevation_data = np.loadtxt(input_filepath, delimiter=",", skiprows=0)
        
    elif file_extension in ['.tif', '.tiff']:
        # Route through tifffile for GeoTIFFs to preserve spatial metadata safely
        if not TIFFFILE_AVAILABLE:
           print("[-] Process Terminated: 'tifffile' library is required for .tif files. Please run: pip install tifffile")
           return
            
        print("[*] GeoTIFF detected. Utilizing 'tifffile' to parse elevation matrix...")
        
        try:
            with tifffile.TiffFile(input_filepath) as tif:
                # 1. Extract the raw elevation array
                raw_elevation_data = tif.asarray().astype(np.float32)
                
                # 2. Extract spatial metadata (ModelPixelScaleTag is standardized as TIFF tag 33550)
                tags = tif.pages[0].tags
                if 'ModelPixelScaleTag' in tags:
                    # ModelPixelScaleTag value is a tuple: (ScaleX, ScaleY, ScaleZ)
                    native_x_res = tags['ModelPixelScaleTag'].value[0]
                    print(f"[+] GeoTIFF Native Spatial Resolution detected: {native_x_res}")
                    # Override the arbitrary UI resolution with the scientifically accurate file resolution
                    spatial_resolution = native_x_res
                
                # 3. Sanitize 'NoData' values (GDAL_NODATA is custom TIFF tag 42113)
                if 'GDAL_NODATA' in tags:
                    ndv = float(tags['GDAL_NODATA'].value)
                    print(f"[*] Sanitizing 'NoData' values (identified as {ndv})")
                    raw_elevation_data[raw_elevation_data == ndv] = np.nan
                    
        except Exception as e:
            print(f"[-] Process Terminated: Failed to read GeoTIFF. Error: {e}")
            return
            
    else:
        print(f"[-] Process Terminated: Unsupported file extension '{file_extension}'.")
        return
    
    print(f"[*] Proceeding with spatial resolution: {spatial_resolution}")
    
    return raw_elevation_data



def convert_to_unreal_format(elevation_data, interpolation_resolution=1.0):
    """
    Transforms and scales a raw Digital Elevation Model (DEM) array to conform 
    to Unreal Engine's standard landscape specifications and sea-level offsets.
    """
    # Sanitize strict zero-values to prevent skewing the global height scale bounds
    elevation_data[elevation_data == 0] = np.nan
    
    # Convert metric elevation data to centimeters (Unreal standard units)
    elevation_cm = elevation_data * CM_PER_METER

    # Calculate the maximum elevation ceiling, executing safely against NaNs
    max_elevation_cm = np.nanmax(elevation_cm)
    if max_elevation_cm == 0 or np.isnan(max_elevation_cm): 
        max_elevation_cm = 1.0 

    # Derive Unreal Engine scaling parameters for the actor transform
    z_axis_scale = max_elevation_cm / UNREAL_Z_SCALE_DIVISOR
    height_scaling_factor = UNREAL_SEA_LEVEL / max_elevation_cm   
    
    # Execute primary scaling transformation against the Unreal 16-bit midpoint (32767)
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

    # Formulate the spatial resolution header for the intermediate caching file
    file_header = f"{elevation_data.shape[1]} {elevation_data.shape[0]} {interpolation_resolution} {z_axis_scale}"

    return file_header, unreal_elevation_data


def calculate_optimal_landscape_config(dem_width, dem_height):
    """
    Analyzes DEM dimensions to iteratively compute the most memory-efficient 
    Unreal Engine landscape configuration that fully encompasses the designated bounds.
    """
    # Valid architectural bounds for Unreal Engine Landscapes (Must adhere strictly to these)
    VALID_QUADS = [63, 127, 255]
    VALID_SECTIONS = [1, 2]
    
    best_area = float('inf')
    best_config = None

    # Evaluate all valid permutations of Quads and Sections to find the tightest fitting grid
    for quads in VALID_QUADS:
        for sections in VALID_SECTIONS:
            vertices_per_comp = quads * sections
            
            # Apply ceiling division to ensure the generated component grid fully encompasses the DEM data
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

    # Halt execution if the DEM dimensions drastically exceed standard single-landscape capability
    if not best_config:
        print("[-] DEM dimensions exceed the maximum 50x50 component threshold. Consider world partitioning.")
        return None
        
    return best_config

# FIX: Added 'base_filename' parameter with a default fallback to ensure nothing breaks
def create_unreal_heightmap(unreal_elevation_data, dem_width, dem_height, landscape_config, output_map_directory, base_filename="lunar_terrain"):
 
    optimal_comp_x, optimal_comp_y, quads, sections, final_width, final_height = landscape_config

    print(f"[+] Optimal Setup Found: {quads} Quads, {sections} Sections.")
    print(f"[*] Component Layout: {optimal_comp_x}x by {optimal_comp_y}y")
    print(f"[*] Final Vertices: {final_width}x by {final_height}y (DEM bounds: {dem_width}x by {dem_height}y)")

    # =========================================================================
    # 4. PREPARE ELEVATION DATA FOR 16-BIT EXPORT
    # =========================================================================
    print("[*] Padding and casting elevation data to 16-bit format...")
    
    # Apply edge padding to the array to perfectly align with the final landscape bounds.
    # This mitigates "cliff" edge artifacts and fulfills Unreal's strict vertex math requirements.
    pad_y = max(0, final_height - dem_height)
    pad_x = max(0, final_width - dem_width)
    padded_grid = np.pad(unreal_elevation_data, ((0, pad_y), (0, pad_x)), mode='edge')

    # FIX: Removed the double-normalization math. 
    # The data was already scaled to Unreal's sea level (32767) in convert_to_unreal_format.
    # We simply clip to prevent overflow and cast to Little-Endian 16-bit ('<u2') required by Unreal.
    min_elevation = np.min(unreal_elevation_data)
    max_elevation = np.max(unreal_elevation_data)
    elevation_range = max(1.0, max_elevation - min_elevation)
    normalized_grid = ((padded_grid - min_elevation) / elevation_range) * UINT16_MAX
    heightmap_data = np.clip(normalized_grid, 0, UINT16_MAX).astype('<u2')

    # =========================================================================
    # 5. EXPORT NATIVE .R16 HEIGHTMAP AND METADATA
    # =========================================================================
    # Dynamically construct the filename using the original input name
    target_heightmap_name = f"{base_filename}_heightmap.r16"
    target_metadata_name  = f"{base_filename}_heightmap.json"
    
    heightmap_filepath = os.path.join(output_map_directory, target_heightmap_name).replace("\\", "/")
    metadata_filepath  = os.path.join(output_map_directory, target_metadata_name).replace("\\", "/")
    
    # Purge existing files to prevent partial overwrites or locking exceptions
    for file_path in [heightmap_filepath, metadata_filepath]:
        if os.path.exists(file_path):
            try: os.remove(file_path)
            except OSError: pass
    
    try:
        # Export the 16-bit array to a binary file via direct memory dump for optimized I/O performance
        with open(heightmap_filepath, "wb") as binary_file:
            heightmap_data.tofile(binary_file) 
            binary_file.flush()
            os.fsync(binary_file.fileno()) # Force the OS buffer to flush to disk
        
        file_size_mb = os.path.getsize(heightmap_filepath) / (1024 * 1024)
        print(f"[+] SUCCESS: R16 file generated at {target_heightmap_name}. Size: {file_size_mb:.2f} MB")
        
    except Exception as e:
        print(f"[-] Critical I/O failure while writing the R16 file: {e}")
        
    # Generate JSON metadata to assist with automated dimension resolution during future imports
    with open(metadata_filepath, "w") as json_file:
        json.dump({"width": final_width, "height": final_height, "bpp": 16}, json_file)