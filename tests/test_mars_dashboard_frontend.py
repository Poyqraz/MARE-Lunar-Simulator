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


@pytest.mark.parametrize("scenario", ["hung_status", "rover_disconnected", "goal_timeout"])
def test_adapter_link_timeouts_and_uncertain_commands(scenario):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed for the JavaScript adapter behavior test")
    script = Path(__file__).parent / "js" / "dashboard_adapter_link.js"
    result = subprocess.run([node, str(script), scenario], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
