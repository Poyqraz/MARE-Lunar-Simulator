"""Run only in a dedicated UE editor process via mars_rover.unreal_check.

This verifies editor import/save contracts, not visual appearance or rover motion.
"""
import json
import os
from pathlib import Path
import time

import unreal
import mars_setup

unreal.EditorPythonScriptingLibrary.set_keep_python_script_alive(True)
report_path = Path(os.environ["MARE_MARS_REPORT"])
started = time.monotonic()

try:
    version = unreal.SystemLibrary.get_engine_version()
    if not version.startswith("5.7."):
        raise RuntimeError(f"This acceptance runner targets Unreal 5.7, got {version}")
    result = mars_setup.build(level_path=os.environ["MARE_MARS_LEVEL"],
                              mode=os.environ.get("MARE_MARS_MODE", "simulation"),
                              report_path=str(report_path))
except Exception as error:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({"status": "failed", "error": str(error),
                                       "visual_qa_passed": False}) + "\n", encoding="utf-8")
    unreal.log_error(str(error))
    unreal.SystemLibrary.quit_editor()
else:
    def finish(delta):
        if result["status"] == "importing" and time.monotonic() - started < 120:
            return
        if result["status"] == "importing":
            report_path.write_text(json.dumps({"status": "failed", "error": "Editor import timed out",
                                               "visual_qa_passed": False}) + "\n", encoding="utf-8")
        unreal.unregister_slate_post_tick_callback(_finish_handle)
        unreal.SystemLibrary.quit_editor()

    _finish_handle = unreal.register_slate_post_tick_callback(finish)
