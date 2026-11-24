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


@pytest.mark.parametrize("scenario", ["trail_error", "empty_trail", "attitude", "stale_telemetry"])
def test_adapter_audit_fixes(scenario):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed for the JavaScript adapter behavior test")
    script = Path(__file__).parent / "js" / "dashboard_adapter_audit.js"
    result = subprocess.run([node, str(script), scenario], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_panels_without_a_backend_say_so_and_carry_no_live_legend():
    html = (Path(__file__).parents[1] / "mars_rover" / "dashboard_assets" / "index.html").read_text(encoding="utf-8")
    for tile in ("f-depth", "f-mask", "f-shadow", "f-events", "f-spad", "f-rear_mask", "f-rear_shadow"):
        start = html.index(f'id="{tile}"')
        assert "NO BACKEND" in html[start:html.index("</div>", start)], tile
    assert "FeedLegends.attach(socket, { depth: [$('f-depth_gt')]" in html and "shadow: [] }" in html
    # LAST GOAL follows the accepted mission goal, not the click.
    click = html[html.index("window.addEventListener('mouseup'"):html.index("socket.emit('send_goal'")]
    assert "t-goal" not in click


def test_unreal_viewport_link_tries_this_service_then_the_ros_overview(monkeypatch):
    import importlib
    import sys
    import types

    fake = types.SimpleNamespace(log=lambda *_: None, register_slate_post_tick_callback=lambda f: "handle",
                                 unregister_slate_post_tick_callback=lambda h: None)
    monkeypatch.setitem(sys.modules, "unreal", fake)
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "Content" / "Python"))
    sys.modules.pop("rover_cameras", None)
    rover_cameras = importlib.import_module("rover_cameras")
    assert rover_cameras.DASHBOARD_URLS[0] == "http://127.0.0.1:8766/viewport_camera"
    tried = []

    def urlopen(url, timeout):
        tried.append(url.split("?")[0])
        link["stop"].set()
        raise OSError("refused")

    monkeypatch.setattr(rover_cameras.urllib.request, "urlopen", urlopen)
    link = {"url": rover_cameras.DASHBOARD_URLS[0], "urls": rover_cameras.DASHBOARD_URLS, "applied": "idle",
            "stop": __import__("threading").Event()}
    rover_cameras._poll_loop(link)
    assert tried == [rover_cameras.DASHBOARD_URLS[0]] and link["url"] == rover_cameras.DASHBOARD_URLS[1]
    assert link["wanted"] is None
    sys.modules.pop("rover_cameras", None)
