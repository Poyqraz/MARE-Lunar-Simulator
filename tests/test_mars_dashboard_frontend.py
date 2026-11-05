import shutil
import subprocess
from pathlib import Path

import pytest


def test_no_route_has_no_camera_overlay_request():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed for the JavaScript adapter behavior test")
    script = Path(__file__).parent / "js" / "dashboard_adapter_no_route.js"
    subprocess.run([node, str(script)], check=True, capture_output=True, text=True, timeout=10)
