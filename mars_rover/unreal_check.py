"""Launch a dedicated UE 5.7 process and require an import/readback JSON report.

    python -m mars_rover.unreal_check --editor "C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor.exe"

This does not classify visual correctness or run rover/autonomy acceptance.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import uuid


def run_validation(editor, *, mode="simulation", project_root=None, timeout_s=600):
    if mode not in ("simulation", "orbital_reference"):
        raise ValueError("Invalid scene mode")
    root = (Path(project_root) if project_root else Path(__file__).resolve().parents[1]).resolve()
    editor = Path(editor)
    if not editor.is_file():
        raise FileNotFoundError("Provide the UE 5.7 UnrealEditor.exe path")
    project = root / "Moon_Simulator.uproject"
    if not project.is_file():
        raise FileNotFoundError(project)
    run_id = uuid.uuid4().hex[:12]
    folder = root / "Saved/Mars"
    folder.mkdir(parents=True, exist_ok=True)
    report = folder / f"acceptance_{run_id}.json"
    log = folder / f"editor_{run_id}.log"
    environment = os.environ.copy()
    environment.update(MARE_MARS_REPORT=str(report), MARE_MARS_LEVEL=f"/Game/Mars/QA_{run_id}", MARE_MARS_MODE=mode)
    command = [str(editor.resolve()), str(project.resolve()), "-unattended", "-nosound", "-stdout",
               "-FullStdOutLogOutput", f"-ExecutePythonScript={root.resolve() / 'tools/unreal_mars_smoke.py'}"]
    try:
        with log.open("w", encoding="utf-8") as stream:
            process = subprocess.run(command, cwd=root, env=environment, stdout=stream,
                                     stderr=subprocess.STDOUT, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"Dedicated UE process timed out; inspect {log}") from error
    if not report.is_file():
        raise RuntimeError(f"Unreal produced no acceptance report; inspect {log}")
    result = json.loads(report.read_text(encoding="utf-8"))
    if (process.returncode != 0 or result.get("status") != "saved" or
            result.get("heightmap_verified") is not True or result.get("collision_verified") is not True):
        raise RuntimeError(f"Unreal import/readback/collision failed; inspect {report} and {log}")
    return {"report_path": str(report), "log_path": str(log), "result": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--editor", required=True, type=Path)
    parser.add_argument("--mode", choices=("simulation", "orbital_reference"), default="simulation")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    try:
        result = run_validation(args.editor, mode=args.mode, timeout_s=args.timeout)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
    print(json.dumps(result, indent=2))
    print("Editor heightmap readback and sampled collision passed. Visual QA and rover motion remain separate.")


if __name__ == "__main__":
    main()
