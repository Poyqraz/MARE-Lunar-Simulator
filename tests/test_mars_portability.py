"""Hashed science data must survive Git for Windows checkout unchanged."""
from pathlib import Path
import subprocess


def test_hashed_csv_survives_autocrlf_checkout(tmp_path):
    root = Path(__file__).parents[1]
    repo, checkout = tmp_path / "repo", tmp_path / "checkout"
    repo.mkdir()
    checkout.mkdir()
    path = repo / "Content/Mars/Jezero"
    path.mkdir(parents=True)
    expected = b"1 2\n3 4\n"
    (path / "elevation.csv").write_bytes(expected)
    (repo / ".gitattributes").write_bytes((root / ".gitattributes").read_bytes())
    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    git("init", "-q")
    git("add", ".")
    git("-c", "core.autocrlf=true", "checkout-index", "--all", f"--prefix={checkout.as_posix()}/")
    assert (checkout / "Content/Mars/Jezero/elevation.csv").read_bytes() == expected
