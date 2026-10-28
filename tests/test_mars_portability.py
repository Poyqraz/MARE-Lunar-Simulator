"""Hashed science data must survive Git for Windows checkout unchanged."""
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize("filename,expected", [("elevation.csv", b"1 2\n3 4\n"),
                                             ("source_dem.xml", b"<metadata>\n</metadata>\n")])
def test_hashed_data_survives_autocrlf_checkout(tmp_path, filename, expected):
    root = Path(__file__).parents[1]
    repo, checkout = tmp_path / "repo", tmp_path / "checkout"
    repo.mkdir()
    checkout.mkdir()
    path = repo / "Content/Mars/Jezero"
    path.mkdir(parents=True)
    (path / filename).write_bytes(expected)
    (repo / ".gitattributes").write_bytes((root / ".gitattributes").read_bytes())
    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    git("init", "-q")
    git("add", ".")
    git("-c", "core.autocrlf=true", "checkout-index", "--all", f"--prefix={checkout.as_posix()}/")
    assert (checkout / "Content/Mars/Jezero" / filename).read_bytes() == expected
