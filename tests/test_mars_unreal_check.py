import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mars_rover.unreal_check import run_validation


def setup_project(tmp_path):
    editor = tmp_path / "engine with spaces/UnrealEditor.exe"
    editor.parent.mkdir()
    editor.touch()
    root = tmp_path / "project with spaces"
    root.mkdir()
    (root / "Moon_Simulator.uproject").write_text("{}")
    return editor, root


def test_launcher_uses_argument_list_and_requires_verified_report(tmp_path, monkeypatch):
    editor, root = setup_project(tmp_path)
    def run(command, **kwargs):
        assert isinstance(command, list)
        assert command[1] == str(root / "Moon_Simulator.uproject")
        assert "shell" not in kwargs
        report = Path(kwargs["env"]["MARE_MARS_REPORT"])
        report.write_text(json.dumps({"status": "saved", "heightmap_verified": True, "visual_qa_passed": False}))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("mars_rover.unreal_check.subprocess.run", run)
    result = run_validation(editor, project_root=root)
    assert result["result"]["visual_qa_passed"] is False


@pytest.mark.parametrize("returncode,report", [
    (0, None), (1, {"status": "saved", "heightmap_verified": True}),
    (0, {"status": "failed", "heightmap_verified": False}),
])
def test_process_exit_alone_cannot_report_success(tmp_path, monkeypatch, returncode, report):
    editor, root = setup_project(tmp_path)
    def run(command, **kwargs):
        if report:
            Path(kwargs["env"]["MARE_MARS_REPORT"]).write_text(json.dumps(report))
        return SimpleNamespace(returncode=returncode)
    monkeypatch.setattr("mars_rover.unreal_check.subprocess.run", run)
    with pytest.raises(RuntimeError):
        run_validation(editor, project_root=root)


def test_relative_project_root_does_not_make_nested_report_paths(tmp_path, monkeypatch):
    editor, root = setup_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    def run(command, **kwargs):
        report = Path(kwargs["env"]["MARE_MARS_REPORT"])
        assert report.is_absolute()
        assert kwargs["cwd"] == root
        report.write_text(json.dumps({"status": "saved", "heightmap_verified": True}))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("mars_rover.unreal_check.subprocess.run", run)
    run_validation(editor, project_root=Path(root.name))
