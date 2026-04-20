"""
Procedural Lunar Terrain Generator & Visualizer
-----------------------------------------------
This module provides a command-line interface (CLI) tool to procedurally 
generate continuous 3D elevation maps simulating lunar surfaces.

The pipeline utilizes Fractal Brownian Motion (fBM) for macro-terrain (hills), 
stochastic collision-aware placement for micro-terrain (craters), and 
sub-surface dithering to prevent quantization artifacts (banding) during 
3D engine rendering.

Configurations are loaded dynamically via YAML, and outputs are serialized 
into standard CSV and NumPy binary formats for downstream engine ingestion.
"""

import os
import sys
import yaml
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.ndimage import gaussian_filter

# =========================================================================
# CONFIGURATION INGESTION & ENVIRONMENT SETUP
# =========================================================================

# Initialize argument parser for CLI execution
parser = argparse.ArgumentParser(description="Procedural Lunar Terrain Generator")
parser.add_argument(
    "-c", "--config", 
    type=str, 
    default="config/settings.yaml", 
    help="Path to the YAML configuration file (default: config/settings.yaml)"
)
args = parser.parse_args()

CONFIG_PATH = args.config
CONFIG_DIR = os.path.dirname(CONFIG_PATH)
OUTPUT_DIR = "outputs"

# Ensure required directory structures exist before execution
if CONFIG_DIR:
    os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Generate a default configuration template if the specified file is missing
if not os.path.exists(CONFIG_PATH):
    print(f"[*] Configuration file not found. Initializing default at '{CONFIG_PATH}'")
    default_yaml = """# ==========================================
# LUNAR TERRAIN GENERATOR CONFIGURATION
# ==========================================

# --- Spatial Dimensions & Base Level ---
ROWS: 1000
COLS: 1000
BASE_ELEVATION: 40.0
RANDOM_SEED: null           # Set to an integer to enforce deterministic generation

# --- Macro-Terrain (Low-Frequency Noise) ---
MACRO_ELEVATION_MIN: 0.5    # Minimum elevation variance (meters)
MACRO_ELEVATION_MAX: 1.0    # Maximum elevation variance (meters)

# --- Micro-Terrain (High-Frequency Noise / Dithering) ---
MICRO_ROUGHNESS: 0.001      # Amplitude of Gaussian noise applied to prevent banding

# --- Crater Morphology ---
CRATER_DENSITY: 0.00001     # Area multiplier determining total crater count
CRATER_MIN_RADIUS_PCT: 0.01 # Minimum radius bounds (percentage of max map dimension)
CRATER_MAX_RADIUS_PCT: 0.12 # Maximum radius bounds (percentage of max map dimension)
CRATER_DEPTH_RATIO: 0.01    # Depth calculation ratio relative to crater radius
CRATER_RIM_HEIGHT_RATIO: 0.2 # Ejecta rim height relative to internal crater depth

# --- Post-Processing ---
EROSION_BLUR_DIVISOR: 50.0  # Dynamic blur scaling. Lower values = stronger erosion smoothing.

# --- I/O Serialization ---
EXPORT_CSV: true
EXPORT_NPY: true
"""
    with open(CONFIG_PATH, 'w') as f:
        f.write(default_yaml.strip())

# Parse and load YAML configuration into runtime variables
print(f"[*] Ingesting parameters from '{CONFIG_PATH}'")
with open(CONFIG_PATH, 'r') as f:
    config = yaml.safe_load(f)

# Map Configuration Variables
ROWS = config.get('ROWS', 1000)
COLS = config.get('COLS', 1000)
BASE_ELEVATION = float(config.get('BASE_ELEVATION', 40.0))
RANDOM_SEED = config.get('RANDOM_SEED', None)

# Noise Generation Variables
MACRO_ELEVATION_MIN = float(config.get('MACRO_ELEVATION_MIN', 0.5))
MACRO_ELEVATION_MAX = float(config.get('MACRO_ELEVATION_MAX', 1.0))
MICRO_ROUGHNESS = float(config.get('MICRO_ROUGHNESS', 0.001))

# Impact Morphological Variables
CRATER_DENSITY = float(config.get('CRATER_DENSITY', 0.00001))
CRATER_MIN_RADIUS_PCT = float(config.get('CRATER_MIN_RADIUS_PCT', 0.01))
CRATER_MAX_RADIUS_PCT = float(config.get('CRATER_MAX_RADIUS_PCT', 0.12))
CRATER_DEPTH_RATIO = float(config.get('CRATER_DEPTH_RATIO', 0.01))
CRATER_RIM_HEIGHT_RATIO = float(config.get('CRATER_RIM_HEIGHT_RATIO', 0.2))

# Post-Processing & Output Variables
EROSION_BLUR_DIVISOR = float(config.get('EROSION_BLUR_DIVISOR', 50.0))
EXPORT_CSV = config.get('EXPORT_CSV', True)
EXPORT_NPY = config.get('EXPORT_NPY', True)


# =========================================================================
# CORE GENERATION LOGIC
# =========================================================================

def add_crater(matrix, center_row, center_col, radius, depth):
    """
    Applies a procedural crater to the target elevation matrix using a 
    parabolic impact model and an exponentially decaying ejecta rim.
    
    Performance Optimization:
    Calculates localized changes via a bounding box subset rather than 
    evaluating the full n-dimensional array, reducing time complexity.

    Args:
        matrix (np.ndarray): The target elevation map.
        center_row (int): Y-axis origin of the impact.
        center_col (int): X-axis origin of the impact.
        radius (float): The base radius of the crater bowl.
        depth (float): Maximum vertical displacement at the center of the bowl.
    """
    # Define bounding box localized to the impact footprint (radius * 1.5 allows for rim)
    max_dist = int(np.ceil(radius * 1.5))
    r_min = max(0, center_row - max_dist)
    r_max = min(ROWS, center_row + max_dist + 1)
    c_min = max(0, center_col - max_dist)
    c_max = min(COLS, center_col + max_dist + 1)

    # Abort if the localized bounding box falls completely outside the map bounds
    if r_min >= r_max or c_min >= c_max:
        return

    # Generate a localized coordinate grid for rapid distance calculations
    r_grid, c_grid = np.ogrid[r_min:r_max, c_min:c_max]
    dist = np.sqrt((r_grid - center_row)**2 + (c_grid - center_col)**2)

    # Segregate spatial zones: Internal impact bowl vs. external ejecta rim
    bowl_mask = dist <= radius
    rim_mask = (dist > radius) & (dist <= radius * 1.5)

    local_matrix = matrix[r_min:r_max, c_min:c_max]

    # Model the internal parabolic depression
    local_matrix[bowl_mask] -= depth * (1 - (dist[bowl_mask] / radius)**2)

    # Model the external rim using quadratic decay for a smooth morphological blend
    rim_dist_normalized = (dist[rim_mask] - radius) / (radius * 0.5)
    rim_height = (depth * CRATER_RIM_HEIGHT_RATIO) * (1 - rim_dist_normalized)**2
    local_matrix[rim_mask] += rim_height


def generate_and_save_data():
    """
    Executes the procedural generation pipeline:
    1. Base initialization
    2. Macro-terrain noise injection
    3. Structural Gaussian smoothing
    4. Collision-aware impact processing (Craters)
    5. Sub-surface dithering (Anti-banding)
    6. File Serialization
    
    Returns:
        np.ndarray: The finalized 2D elevation matrix.
    """
    print(f"[*] Initializing {ROWS}x{COLS} primary elevation matrix...")
    
    # Establish deterministic vs. stochastic behavior based on config
    if RANDOM_SEED is not None:
        np.random.seed(RANDOM_SEED)
        print(f"[*] State locked. Using deterministic seed: {RANDOM_SEED}")
    else:
        np.random.seed(None)
        print("[*] State open. Proceeding with stochastic generation...")
        
    elevation_matrix = np.full((ROWS, COLS), BASE_ELEVATION)
    max_dimension = max(ROWS, COLS)

    # --- Phase 1: Macro-Terrain Construction ---
    print(f"[*] Synthesizing {MACRO_ELEVATION_MIN}m - {MACRO_ELEVATION_MAX}m macro-terrain features...")
    macro_noise = np.random.normal(loc=0.0, scale=1.0, size=(ROWS, COLS))
    macro_noise = gaussian_filter(macro_noise, sigma=max_dimension / 10.0)
    
    # Normalize noise matrix and map to configured elevation amplitudes
    macro_noise -= np.min(macro_noise)
    macro_noise /= np.max(macro_noise)
    target_differential = np.random.uniform(MACRO_ELEVATION_MIN, MACRO_ELEVATION_MAX)
    macro_noise = (macro_noise * target_differential) - (target_differential / 2.0)
    elevation_matrix += macro_noise

    # Apply heavy structural smoothing to ensure natural geological formations
    dynamic_sigma = max(1.0, max_dimension / EROSION_BLUR_DIVISOR)
    elevation_matrix = gaussian_filter(elevation_matrix, sigma=dynamic_sigma)

    # --- Phase 2: Impact Generation & Collision Handling ---
    total_area = ROWS * COLS
    num_craters = int(total_area * CRATER_DENSITY)
    
    placed_craters = []
    attempts = 0
    max_attempts = num_craters * 10  # Hard threshold to prevent infinite `while` loops
    
    print(f"[*] Processing stochastic placement for {num_craters} impacts...")
    
    while len(placed_craters) < num_craters and attempts < max_attempts:
        attempts += 1
        
        # Calculate random spatial coordinates and physical morphology limits
        r_center = np.random.randint(0, ROWS)
        c_center = np.random.randint(0, COLS)
        
        min_rad = max_dimension * CRATER_MIN_RADIUS_PCT
        max_rad = max_dimension * CRATER_MAX_RADIUS_PCT
        # Exponential bias applied via exponentiation to favor smaller impacts
        rad = min_rad + (max_rad - min_rad) * (np.random.random() ** 3)
        
        # Determine collision thresholds
        is_overlapping = False
        required_margin = rad * 1.5  # Account for the extended ejecta rim footprint
        
        # Execute Euclidean distance comparisons against registered impacts
        for (pr, pc, prad) in placed_craters:
            distance = np.sqrt((r_center - pr)**2 + (c_center - pc)**2)
            if distance < (required_margin + (prad * 1.5)):
                is_overlapping = True
                break
        
        # Register and process valid impact events
        if not is_overlapping:
            dep = rad * CRATER_DEPTH_RATIO   
            add_crater(elevation_matrix, r_center, c_center, rad, dep)
            placed_craters.append((r_center, c_center, rad))

    # --- Phase 3: High-Frequency Noise & Post-Processing ---
    # Inject high-frequency Gaussian noise to act as 3D spatial dithering,
    # preventing integer-rounding quantization artifacts (terracing/banding).
    roughness = np.random.normal(loc=0.0, scale=MICRO_ROUGHNESS, size=(ROWS, COLS))
    elevation_matrix += roughness

    # Apply sub-pixel anti-aliasing to soften harsh noise artifacts
    elevation_matrix = gaussian_filter(elevation_matrix, sigma=0.8)

    # --- Phase 4: Data Serialization & File I/O ---
    if EXPORT_CSV:
        print("[*] Serializing CSV datasets...")
        ele_csv_path = os.path.join(OUTPUT_DIR, 'generated_elevationMap_moon.csv')
        pd.DataFrame(elevation_matrix).to_csv(ele_csv_path, index=False, header=False, sep=' ')
        
        # Generate edge-masked soil layer for 3D engine material blending
        soil_matrix = np.zeros((ROWS, COLS), dtype=int) 
        soil_matrix[1:-1, 1:-1] = 1
        
        soil_csv_path = os.path.join(OUTPUT_DIR, 'generated_soilMap_edges_0.csv')
        pd.DataFrame(soil_matrix).to_csv(soil_csv_path, index=False, header=False, sep=' ')

    if EXPORT_NPY:
        print("[*] Serializing NumPy binaries...")
        npy_path = os.path.join(OUTPUT_DIR, 'generated_elevationMap_moon.npy')
        np.save(npy_path, elevation_matrix)

    print(f"[+] Pipeline completed successfully. Valid impacts registered: {len(placed_craters)}")
    return elevation_matrix


def preview_terrain(elevation_matrix):
    """
    Constructs a 2D topographical heatmap and a 3D structural mesh utilizing 
    Matplotlib to visually debug the procedural generation outputs.
    
    Args:
        elevation_matrix (np.ndarray): The finalized 2D elevation matrix to render.
    """
    print("[*] Generating structural preview telemetry... (Terminate window to exit)")
    
    # Establish rendering grid coordinates
    X = np.arange(COLS)
    Y = np.arange(ROWS)
    X, Y = np.meshgrid(X, Y)

    fig = plt.figure(figsize=(14, 6))

    # Compile 2D topological contour map
    ax1 = fig.add_subplot(121)
    contour = ax1.contourf(X, Y, elevation_matrix, cmap='magma', levels=50)
    fig.colorbar(contour, ax=ax1, shrink=0.7, label='Elevation (Meters)')
    ax1.set_title('2D Topographical Analysis')
    ax1.set_aspect('equal') 

    # Compile 3D structural downsampled surface mesh
    ax2 = fig.add_subplot(122, projection='3d')
    surf = ax2.plot_surface(X, Y, elevation_matrix, cmap='magma', edgecolor='none', alpha=0.9, rcount=150, ccount=150)
    ax2.set_title('3D Structural Preview')
    
    # Set localized camera view and constraint bounds
    ax2.view_init(elev=45, azim=-45)
    z_min, z_max = np.min(elevation_matrix), np.max(elevation_matrix)
    z_range = max(1.0, z_max - z_min)
    ax2.set_zlim(z_min - (z_range * 0.5), z_max + (z_range * 0.5))

    plt.tight_layout()
    plt.show()

# =========================================================================
# RUNTIME EXECUTION
# =========================================================================

if __name__ == "__main__":
    # Execute pipeline and capture final array
    final_elevation_matrix = generate_and_save_data()
    # Trigger UI debug visualization
    preview_terrain(final_elevation_matrix)