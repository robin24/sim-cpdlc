"""The release plumbing: the version strings agree and the build is gated.

A checkout used to say 0.1.0 while the installer said 0.3.1 and the tags said
2.x, because the release job rewrote the versions and never committed them
(audit M-10). RELEASING.md now has the maintainer commit the bump before
tagging; these tests catch the drift before the tag does.
"""

import datetime
import re
import shutil
import subprocess
import sys
from pathlib import Path

from packaging.version import Version

from src.config import APP_VERSION

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_the_version_strings_agree():
    info = read("version_info.txt")
    iss = read("sim-cpdlc.iss")
    parts = tuple(APP_VERSION.split("."))

    assert re.search(r"filevers=\((\d+), (\d+), (\d+), (\d+)\)", info).groups() == parts + ("0",)
    assert re.search(r"prodvers=\((\d+), (\d+), (\d+), (\d+)\)", info).groups() == parts + ("0",)
    assert re.search(r"u'FileVersion', u'([\d.]+)'", info).group(1) == APP_VERSION
    assert re.search(r"u'ProductVersion', u'([\d.]+)'", info).group(1) == APP_VERSION
    assert re.search(r'#define MyAppVersion "([\d.]+)"', iss).group(1) == APP_VERSION


def test_the_version_is_a_plain_release_number():
    """The update checker compares it with packaging.version, the tag is vX.Y.Z,
    and 0.1.0 would make every release look like an update."""
    assert APP_VERSION.count(".") == 2
    assert Version(APP_VERSION) >= Version("2.1.2")


def test_the_build_tools_are_not_runtime_requirements():
    runtime = read("requirements.txt")
    build = read("requirements-build.txt")

    assert "pyinstaller" not in runtime.lower()
    assert "pyinstaller==" in build.lower()
    assert "-r requirements.txt" in build
    assert re.search(r"^SimConnect==\d", runtime, re.M)


def test_the_release_builds_only_after_the_tests_pass_on_the_tagged_version():
    workflow = read(".github/workflows/build-and-release.yml")

    assert "needs: test" in workflow
    assert "APP_VERSION" in workflow
    assert "update_version.py" not in workflow
    assert "Check that the code carries the tagged version" in workflow
    assert "src/config.py" in workflow
    assert 'TAG_VERSION: ${{ steps.get_version.outputs.version }}' in workflow


def test_the_bump_script_refreshes_the_copyright_year(tmp_path):
    """version_info.txt used to say "Copyright (c) 2025 Robin Kipp" forever,
    because update_version.py bumped the version numbers but never touched
    the LegalCopyright year."""
    original_app_version = APP_VERSION

    version_info_copy = tmp_path / "version_info.txt"
    iss_copy = tmp_path / "sim-cpdlc.iss"
    config_copy = tmp_path / "config.py"
    shutil.copy(ROOT / "version_info.txt", version_info_copy)
    shutil.copy(ROOT / "sim-cpdlc.iss", iss_copy)
    shutil.copy(ROOT / "src" / "config.py", config_copy)

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "update_version.py"),
            "9.9.9",
            "--version-file", str(version_info_copy),
            "--iss-file", str(iss_copy),
            "--config-file", str(config_copy),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    updated_info = version_info_copy.read_text(encoding="utf-8")
    assert "filevers=(9, 9, 9, 0)" in updated_info
    assert f"Copyright (c) {datetime.date.today().year} Robin Kipp" in updated_info
    assert 'APP_VERSION = "9.9.9"' in config_copy.read_text(encoding="utf-8")

    # The real files are never touched -- only the tmp_path copies are.
    assert APP_VERSION == original_app_version
