"""
Lunar Terrain Generator & Visualizer (Final Parameterized Version)
------------------------------------------------------------------
Procedurally generates a lunar surface. 
Includes adjustable, pronounced crater rims and anti-banding dithering.
Order of Operations: Hills -> Smooth Hills -> Craters -> Dither -> Polish.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.ndimage import gaussian_filter

# =========================================================================
# CONFIGURATION & PARAMETERS
# =========================================================================

# --- Dimensions & Base ---
ROWS = 1000
COLS = 1000
BASE_ELEVATION = 40.0
RANDOM_SEED = None               # Set to 'None' for infinite variations, or a number to lock it.

# --- Macro-Terrain (Rolling Hills) ---
MACRO_ELEVATION_MIN = 0.5        # Minimum height differential for hills
MACRO_ELEVATION_MAX = 1.0        # Maximum height differential for hills

# --- Micro-Terrain (Surface Noise) ---
MICRO_ROUGHNESS = 0.001          # Very subtle dithering to prevent banding

# --- Craters ---
CRATER_DENSITY = 0.00001         # Multiplier for total number of craters
CRATER_MIN_RADIUS_PCT = 0.01     # Minimum crater radius (as % of largest map dimension)
CRATER_MAX_RADIUS_PCT = 0.12     # Maximum crater radius (as % of largest map dimension)
CRATER_DEPTH_RATIO = 0.01        # Depth multiplier relative to crater radius 
CRATER_RIM_HEIGHT_RATIO = 0.2    # 1.0 means the rim pushes up exactly as much as the bowl digs down

# --- Erosion (Smoothing) ---
EROSION_BLUR_DIVISOR = 50.0     

# --- Export Settings ---
EXPORT_CSV = True                
EXPORT_NPY = True                

# =========================================================================

def add_crater(matrix, center_row, center_col, radius, depth):
    """Stamps a parabolic crater with a pronounced raised rim onto the matrix."""
    max_dist = int(np.ceil(radius * 1.5))
    r_min = max(0, center_row - max_dist)
    r_max = min(ROWS, center_row + max_dist + 1)
    c_min = max(0, center_col - max_dist)
    c_max = min(COLS, center_col + max_dist + 1)

    if r_min >= r_max or c_min >= c_max:
        return

    r_grid, c_grid = np.ogrid[r_min:r_max, c_min:c_max]
    dist = np.sqrt((r_grid - center_row)**2 + (c_grid - center_col)**2)

    bowl_mask = dist <= radius
    rim_mask = (dist > radius) & (dist <= radius * 1.5)

    local_matrix = matrix[r_min:r_max, c_min:c_max]

    # 1. Apply The Bowl (Digging down)
    local_matrix[bowl_mask] -= depth * (1 - (dist[bowl_mask] / radius)**2)

    # 2. Apply The Rim (Pushing up)
    rim_dist_normalized = (dist[rim_mask] - radius) / (radius * 0.5)
    rim_height = (depth * CRATER_RIM_HEIGHT_RATIO) * (1 - rim_dist_normalized)**2
    local_matrix[rim_mask] += rim_height

def generate_and_save_data():
    print(f"[*] Generating {ROWS}x{COLS} lunar elevation map...")
    
    if RANDOM_SEED is not None:
        np.random.seed(RANDOM_SEED)
        print(f"[*] Locked to Random Seed: {RANDOM_SEED}")
    else:
        np.random.seed(None)
        print("[*] Using infinite random variations...")
        
    elevation_matrix = np.full((ROWS, COLS), BASE_ELEVATION)
    max_dimension = max(ROWS, COLS)

    # =========================================================================
    # 1. Add Macro-Terrain (Rolling Hills)
    # =========================================================================
    print(f"[*] Generating {MACRO_ELEVATION_MIN}-{MACRO_ELEVATION_MAX}m macro-terrain differential...")
    macro_noise = np.random.normal(loc=0.0, scale=1.0, size=(ROWS, COLS))
    macro_noise = gaussian_filter(macro_noise, sigma=max_dimension / 10.0)
    
    macro_noise -= np.min(macro_noise)
    macro_noise /= np.max(macro_noise)
    
    target_differential = np.random.uniform(MACRO_ELEVATION_MIN, MACRO_ELEVATION_MAX)
    macro_noise = (macro_noise * target_differential) - (target_differential / 2.0)
    elevation_matrix += macro_noise

    # =========================================================================
    # 2. Smooth the Hills heavily BEFORE adding craters
    # =========================================================================
    dynamic_sigma = max(1.0, max_dimension / EROSION_BLUR_DIVISOR)
    elevation_matrix = gaussian_filter(elevation_matrix, sigma=dynamic_sigma)

    # =========================================================================
    # 3. Add Procedural Craters
    # =========================================================================
    total_area = ROWS * COLS
    num_craters = int(total_area * CRATER_DENSITY)
    
    print(f"[*] Planting {num_craters} realistically scaled craters...")
    for _ in range(num_craters):
        r_center = np.random.randint(0, ROWS)
        c_center = np.random.randint(0, COLS)
        
        min_rad = max_dimension * CRATER_MIN_RADIUS_PCT
        max_rad = max_dimension * CRATER_MAX_RADIUS_PCT
        rad = min_rad + (max_rad - min_rad) * (np.random.random() ** 3)
        
        dep = rad * CRATER_DEPTH_RATIO   
        
        add_crater(elevation_matrix, r_center, c_center, rad, dep)

    # =========================================================================
    # 4. Anti-Banding Fix: Add Dithering (Micro-roughness)
    # =========================================================================
    roughness = np.random.normal(loc=0.0, scale=MICRO_ROUGHNESS, size=(ROWS, COLS))
    elevation_matrix += roughness

    # =========================================================================
    # 5. Anti-Banding Fix: Very Light Final Polish 
    # =========================================================================
    elevation_matrix = gaussian_filter(elevation_matrix, sigma=0.8)

    # =========================================================================
    # 6. Export Files
    # =========================================================================
    if EXPORT_CSV:
        print("[*] Saving CSV files...")
        pd.DataFrame(elevation_matrix).to_csv('generated_elevationMap_moon.csv', index=False, header=False, sep=' ')
        
        soil_matrix = np.full((ROWS, COLS), 1, dtype=int)
        soil_matrix[0, :] = 0      
        soil_matrix[-1, :] = 0     
        soil_matrix[:, 0] = 0      
        soil_matrix[:, -1] = 0     
        pd.DataFrame(soil_matrix).to_csv('generated_soilMap_edges_0.csv', index=False, header=False, sep=' ')

    if EXPORT_NPY:
        print("[*] Saving Unreal-ready .npy file...")
        np.save('generated_elevationMap_moon.npy', elevation_matrix)

    print("[+] Generation and export complete!")
    return elevation_matrix

def preview_terrain(elevation_matrix):
    print("[*] Rendering visual preview... (Close the window to exit)")
    
    X = np.arange(COLS)
    Y = np.arange(ROWS)
    X, Y = np.meshgrid(X, Y)

    fig = plt.figure(figsize=(14, 6))

    ax1 = fig.add_subplot(121)
    contour = ax1.contourf(X, Y, elevation_matrix, cmap='magma', levels=50)
    fig.colorbar(contour, ax=ax1, shrink=0.7, label='Elevation')
    ax1.set_title('2D Topographical Heatmap')
    ax1.set_aspect('equal') 

    ax2 = fig.add_subplot(122, projection='3d')
    surf = ax2.plot_surface(X, Y, elevation_matrix, cmap='magma', edgecolor='none', alpha=0.9, rcount=150, ccount=150)
    ax2.set_title('3D Surface Preview')
    
    ax2.view_init(elev=45, azim=-45)
    
    z_min, z_max = np.min(elevation_matrix), np.max(elevation_matrix)
    z_range = max(1.0, z_max - z_min)
    ax2.set_zlim(z_min - (z_range * 0.5), z_max + (z_range * 0.5))

    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    final_elevation_matrix = generate_and_save_data()
    preview_terrain(final_elevation_matrix)