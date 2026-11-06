import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "project.py"


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_test_command_covers_both_repositories():
    result = run_script("test")

    assert result.returncode == 0
    assert str(ROOT) in result.stdout
    assert str(ROOT.parent / "SentientMilk") in result.stdout
    assert "pytest" in result.stdout


def test_build_command_uses_local_sentientmilk_checkout():
    result = run_script("build")

    assert result.returncode == 0
    assert "SENTIENTMILK_FRAMEWORK_PARENT" in result.stdout
    assert str(ROOT.parent / "SentientMilk") in result.stdout
    assert "PyInstaller" in result.stdout
