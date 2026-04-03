"""
Unreal Engine Remote Execution Client
-------------------------------------
This script establishes a network connection to a running instance of Unreal Engine
and triggers the lunar terrain generation pipeline using local data files.
"""

import remote_execution
import time
import os

def send_to_unreal():
    """
    Locates a running Unreal Editor instance and executes the terrain 
    generation script with dynamic path resolution.
    """
    
    # --- 1. Path Configuration ---
    # Resolve the absolute directory of the current script to handle relative file lookups
    base_folder = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
    
    # Define target DEM file and resolution parameters
    dem_file = f"{base_folder}/lunalab.npy"
    spatial_resolution = 0.01

    # --- 2. Remote Connection Setup ---
    # Initialize the Unreal Remote Execution library
    remote_exec = remote_execution.RemoteExecution()
    remote_exec.start()
    
    print(f"[*] Searching for Unreal Engine instances... (Root: {base_folder})")
    
    # Broadcast discovery takes time; wait 2s to populate the remote_nodes list
    time.sleep(2.0) 

    nodes = remote_exec.remote_nodes
    if nodes and len(nodes) > 0:
        # Retrieve the first available engine instance
        first_node = nodes[0]
        
        # Extract the unique Node ID, handling both dict and object return types
        node_id = first_node.get("node_id") if isinstance(first_node, dict) else getattr(first_node, "node_id", None)

        if node_id:
            # Establish a command-level connection to the specific Editor instance
            remote_exec.open_command_connection(node_id)
            
            # --- 3. Command Construction ---
            # We construct a multi-part Python command to execute within Unreal's interpreter:
            # - sys.path.append: Ensures the Editor can find the 'lunar_terrain_generator' module.
            # - importlib.reload: Forces the Editor to use the latest version of the script.
            # - .main(): Triggers the processing logic with our local file paths.
            command = (
                f"import sys; "
                f"sys.path.append('{base_folder}') if '{base_folder}' not in sys.path else None; "
                f"import lunar_terrain_generator; "
                f"import importlib; importlib.reload(lunar_terrain_generator); "
                f"lunar_terrain_generator.main('{dem_file}', {spatial_resolution})"
            )
            
            # Dispatch the command to the Unreal Engine Python environment
            remote_exec.run_command(command)
            print(f"[+] Success: Command dispatched to Node [{node_id}]")
    else:
        # If no nodes are found, verify 'Enable Remote Execution' is toggled in Project Settings
        print("[-] Error: No Unreal instance detected. Ensure 'Remote Execution' is active.")

    # Clean up the network broadcast resources
    remote_exec.stop()

if __name__ == "__main__":
    send_to_unreal()