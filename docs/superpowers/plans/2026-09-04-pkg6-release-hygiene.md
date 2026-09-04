# Package 6: Release, Packaging, Docs and Hygiene — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A release carries one version everywhere and is built only from a tested, tagged commit; a source checkout says it is one; logs never carry a logon code; the docs describe the client as it now behaves; and the leftovers the audit and the earlier packages' reviews listed (dead code, stray files, duplicated gates, hard-coded colours, optional workers) are gone.

**Architecture:** No new subsystem. Release plumbing lives in `RELEASING.md`, the release workflow (a `test` job the build depends on, a tag-versus-`APP_VERSION` check, build tools in `requirements-build.txt`) and a `tests/test_release.py` that keeps the three version strings equal. The About box gets a pure `version_label()`. Logging changes are local to `simbrief.py`, `logging_setup.py`, `config.py`, `connection_manager.py` and `error_reporting.py`. Hygiene is a set of small deletions and one new gate helper, `MainWindow._require_logon(action)`, beside the existing `_require_connection`. The last task makes the network worker a required collaborator and applies the two accessibility conventions the spec names.

**Tech Stack:** Python 3.12+, wxPython 4.2.5, hoppie-connector 0.2.1, `packaging`, pytest 9.1.1 with pytest-timeout, GitHub Actions, PyInstaller 6.20.0, Inno Setup.

## Global Constraints

- Run every command with `C:\Claude\sim-cpdlc\.claude\worktrees\review-25-ceb148\.venv\Scripts\python.exe` (below `$PY`; in Git Bash `PY=/c/Claude/sim-cpdlc/.claude/worktrees/review-25-ceb148/.venv/Scripts/python.exe`). Run the suite from the worktree root as `$PY -m pytest -q -p no:cacheprovider`. Baseline before this plan: 518 passed. The suite must be green at the end of every task.
- Work on branch `claude/pkg6-release-hygiene`, cut from `main` at `a2fc377`, in the worktree `C:\Claude\sim-cpdlc\.claude\worktrees\pkg6-release-hygiene`. Never touch `C:\Claude\sim-cpdlc` itself. Never read `config.json` anywhere (it holds credentials).
- Test-driven: every task writes its failing tests first, runs them to see them fail for the expected reason, then implements. Tests must never reach the network, the real config file, SimBrief, the simulator or a modal dialog (the autouse fixtures in `tests/conftest.py` enforce this; keep using `tests.support` doubles).
- Files this package may change: `RELEASING.md` (new), `requirements-build.txt` (new), `tools/simbrief_probe.py` (new, moved from `src/utils/test_simbrief.py`), `.github/workflows/build-and-release.yml`, `.github/dependabot.yml`, `requirements.txt`, `app.spec`, `.gitignore`, `pytest.ini`, `README.md`, `tests/README.md`, `version_info.txt`, `sim-cpdlc.iss`, `src/config.py`, `src/logging_setup.py`, `src/error_reporting.py`, `src/utils/simbrief.py`, `src/utils/weather_parsing.py`, `src/utils/update_checker.py`, `src/model/connection_manager.py`, `src/model/cpdlc_session.py`, `src/model/message_manager.py`, `src/model/network_worker.py`, `src/model/weather_monitor.py`, `src/controller/polling_controller.py`, `src/gui/main_window.py`, `src/gui/message_view.py`, `src/gui/dialogs/about_dialog.py`, `src/gui/dialogs/connect_dialog.py`, `src/gui/dialogs/telex_dialog.py`, `src/gui/dialogs/altitude_change_dialog.py`, `src/gui/dialogs/direct_request_dialog.py`, `src/gui/dialogs/speed_request_dialog.py`, `src/gui/dialogs/when_can_we_dialog.py`, the deletions of `src/utils/latest_simbrief_ofp.json` and `src/utils/test_simbrief.py`, and anything under `tests/`. Nothing else.
- Exact values: the current release is `2.1.2` (the highest `v*` tag); `APP_VERSION`, `version_info.txt` (`filevers=(2, 1, 2, 0)`, `prodvers=(2, 1, 2, 0)`, `FileVersion`/`ProductVersion` `2.1.2`) and `sim-cpdlc.iss` (`MyAppVersion "2.1.2"`) all say so. Pins: `SimConnect==0.4.26` in `requirements.txt`, `pyinstaller==6.20.0` in `requirements-build.txt`. The About version reads `"{APP_VERSION} (source)"` when `sys.frozen` is not set and `APP_VERSION` otherwise; the copyright reads `"Copyright (c) {datetime.date.today().year} Robin Kipp"`. The SimBrief logger is `logging.getLogger("Sim-CPDLC.simbrief")`. `_require_logon(action)` shows `"You must be logged on to a station to {action}."` with caption `"Not Logged On"` and style `wx.OK | wx.ICON_INFORMATION`. Helper texts use `wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT)`. The Connect dialog's `RadioBox` label is `"Network"`.
- Commit messages: imperative sentence subject, body, trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Git prints CRLF warnings on this machine; they are harmless. Write files with LF endings.
- Spec: `docs/superpowers/specs/2026-09-03-audit-fixes-design.md`, section "Package 6: release, packaging, docs, hygiene". Audit: `docs/audit/2026-09-03-codebase-audit.md` (M-10, L-6, L-8, L-18, L-19, L-20, I-1 to I-5).

## Deviations from the spec (decided while planning; the spec's "Package 6" section is otherwise followed)

1. **The release workflow no longer runs `update_version.py`.** The spec adds a check that fails when `APP_VERSION` differs from the tag; once that check exists, rewriting the versions inside the job only recreates the drift the audit found (M-10). The maintainer runs the script before tagging, as `RELEASING.md` says, and `tests/test_release.py` keeps the three files equal.
2. **The tag check reads `APP_VERSION` with a regular expression** instead of importing `src.config`, so it needs no installed dependencies and runs before `pip install`.
3. **`_check_first_launch` asks `config_file_exists()`** (new in `src/config.py`) instead of importing `CONFIG_FILE` at module level: the test fixture patches `src.config.CONFIG_FILE` at call time, and a module-level copy in the window would not see it.
4. **`WeatherMonitor`, `PollingController`, `CpdlcSession` and `UpdateChecker` take `worker` as a required keyword-only argument** (the package 4 review's pointer): a default of `None` cannot operate and fails only when the first job is submitted.
5. **`NetworkWorker.run_detached` raises `ValueError` for a paced kind** rather than an `assert`, which `python -O` would strip.
6. **The three README items the spec lists are done as written, plus a "Network Behaviour" section** describing the worker, the send spacing, the exit drain and the link announcements the earlier packages introduced (the package 2 and 4 reviews asked for both paragraphs).
7. **`extract_atis_letter` loses its unused `icao` parameter** (audit I-1); its callers and tests drop the argument.

## Design notes

- **Versions.** `update_version.py` already rewrites the three files consistently; Task 1 runs it once with `2.1.2` and adds a test that parses all three. The workflow's `test` job is a copy of `tests.yml`'s job, so a tag on a red tree never builds.
- **Logging.** Records from `Sim-CPDLC.simbrief` propagate to the `Sim-CPDLC` logger's handlers. `config.py` stops creating the user-data directory at import time: `CONFIG_FILE` is computed from `appdirs.user_data_dir` alone, `save_config` creates the directory when it writes, and `get_user_data_dir()` (used by `app.py` and the log file) keeps creating it.
- **Gates.** Every handler that needs a station calls `_require_connection(action)` then `_require_logon(action)` with the same `action` text; the Telex handler needs only the connection.
- **Deletions are verified by grep**, listed in each task; the suite staying green is the test.

---

### Task 1: One version everywhere, and a release that is tested before it is built

**Files:**
- Create: `RELEASING.md`, `requirements-build.txt`, `tests/test_release.py`
- Modify: `.github/workflows/build-and-release.yml`, `.github/dependabot.yml`, `requirements.txt`, `app.spec`, `.gitignore`, `src/config.py:15`, `version_info.txt`, `sim-cpdlc.iss:5`, `tests/README.md`

**Interfaces:**
- Produces: `APP_VERSION == "2.1.2"` (read by Task 2's tests).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_release.py`:

```python
"""The release plumbing: the version strings agree and the build is gated.

A checkout used to say 0.1.0 while the installer said 0.3.1 and the tags said
2.x, because the release job rewrote the versions and never committed them
(audit M-10). RELEASING.md now has the maintainer commit the bump before
tagging; these tests catch the drift before the tag does.
"""

import re
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_release.py`
Expected: four failures — the version strings differ (`0.1.0` / `0.3.1`), `Version("0.1.0") >= Version("2.1.2")` is false, `requirements-build.txt` does not exist, the workflow lacks `needs: test`.

- [ ] **Step 3: Align the three version strings**

Run: `$PY update_version.py 2.1.2`
Expected output: `Successfully updated version to 2.1.2 in all files`. Check with `git diff --stat`: `src/config.py`, `version_info.txt` and `sim-cpdlc.iss` changed and nothing else; `grep -n "2.1.2" src/config.py version_info.txt sim-cpdlc.iss` shows `APP_VERSION = "2.1.2"`, `filevers=(2, 1, 2, 0)`, `prodvers=(2, 1, 2, 0)`, the two `StringStruct` lines and `#define MyAppVersion "2.1.2"`.

- [ ] **Step 4: Split the requirements and pin SimConnect**

`requirements.txt`:

```
hoppie-connector==0.2.1
requests==2.33.1
wxPython==4.2.5
appdirs==1.4.4
packaging==26.2
SimConnect==0.4.26
```

Create `requirements-build.txt`:

```
-r requirements.txt
pyinstaller==6.20.0
```

(`requirements-dev.txt` stays as it is.)

- [ ] **Step 5: Stop the build when SimConnect.dll is missing**

In `app.spec` replace the block from `# Locate SimConnect.dll` to `_sc_binaries = [(_sc_dll, 'SimConnect')]` with:

```python
# Locate SimConnect.dll next to the installed SimConnect package. Without it
# the packaged build starts, but tuning the radio can never work, so a missing
# DLL stops the build instead of shipping a broken installer.
import os
_sc_spec = importlib.util.find_spec('SimConnect')
if not (_sc_spec and _sc_spec.origin):
    raise SystemExit("SimConnect package not found; pip install -r requirements-build.txt")
_sc_dll = os.path.join(os.path.dirname(_sc_spec.origin), 'SimConnect.dll')
if not os.path.isfile(_sc_dll):
    raise SystemExit(f"SimConnect.dll not found at {_sc_dll}")
_sc_binaries = [(_sc_dll, 'SimConnect')]
```

- [ ] **Step 6: Ignore the build outputs and watch the actions**

Append to `.gitignore` (one per line): `installer/` and `.pytest_cache/`.

Append to `.github/dependabot.yml` under `updates:`:

```yaml
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
```

- [ ] **Step 7: Gate the release on the tests and the tag**

Replace `.github/workflows/build-and-release.yml` with:

```yaml
name: Build and Release

on:
  push:
    tags:
      - "v*.*.*"

permissions:
  contents: write  # creating the release needs it

jobs:
  test:
    # Windows to match the build job: this is a Windows app and the GUI tests
    # construct real wx windows.
    runs-on: windows-latest
    timeout-minutes: 15
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.13'
          cache: 'pip'
          cache-dependency-path: |
            requirements.txt
            requirements-dev.txt

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements-dev.txt

      - name: Run tests
        run: pytest

  build-and-release:
    needs: test
    runs-on: windows-latest
    timeout-minutes: 30
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.13'

      - name: Extract version from the tag
        id: get_version
        shell: bash
        run: |
          VERSION=${GITHUB_REF#refs/tags/v}
          echo "version=$VERSION" >> $GITHUB_OUTPUT
          echo "Version extracted: $VERSION"

      - name: Check that the code carries the tagged version
        shell: bash
        run: |
          python - "${{ steps.get_version.outputs.version }}" <<'EOF'
          import re, sys
          tag = sys.argv[1]
          source = open("src/config.py", encoding="utf-8").read()
          app_version = re.search(r'^APP_VERSION = "([^"]+)"', source, re.M).group(1)
          if app_version != tag:
              sys.exit(f"APP_VERSION is {app_version!r} but the tag says {tag!r}: "
                       f"run update_version.py {tag}, commit, and move the tag (see RELEASING.md)")
          print(f"APP_VERSION {app_version} matches the tag")
          EOF

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements-build.txt

      - name: Build with PyInstaller
        run: pyinstaller app.spec

      - name: Run Inno Setup
        uses: robin24/inno-setup-action@v1
        with:
          filepath: ./sim-cpdlc.iss

      - name: Upload Release Asset
        uses: softprops/action-gh-release@v2
        with:
          files: |
            installer/Sim-CPDLC-${{ steps.get_version.outputs.version }}.exe
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] **Step 8: Write `RELEASING.md`**

```markdown
# Releasing Sim-CPDLC

The tag is the version. Every file that carries a version number must say the
same thing before the tag is pushed, and the release workflow refuses to build
when it does not.

1. Pick the version `X.Y.Z` (the last release is the highest `v*` tag).
2. Run `python update_version.py X.Y.Z`. It rewrites `APP_VERSION` in
   `src/config.py`, the four version fields in `version_info.txt` and
   `MyAppVersion` in `sim-cpdlc.iss`.
3. Run `pytest`. `tests/test_release.py` fails if the three files disagree.
4. Commit: `git commit -am "Release X.Y.Z"` and push `main`.
5. Tag and push the tag: `git tag vX.Y.Z && git push origin vX.Y.Z`.

Pushing the tag starts `.github/workflows/build-and-release.yml`: it runs the
test suite, checks that `APP_VERSION` equals the tag, installs
`requirements-build.txt`, builds the executable with PyInstaller (the build
stops if `SimConnect.dll` is missing), builds the installer with Inno Setup and
attaches `Sim-CPDLC-X.Y.Z.exe` to a GitHub release for the tag.

If the version check fails, fix the files, commit, move the tag
(`git tag -f vX.Y.Z && git push -f origin vX.Y.Z`) and the workflow runs again.

A checkout that is not a packaged build shows `X.Y.Z (source)` in
`File > About` and never checks for updates automatically.
```

- [ ] **Step 9: Run the tests and the suite**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_release.py`
Expected: 4 passed.

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all pass (the update checker tests compare against `APP_VERSION` symbolically; if one hard-codes `0.1.0`, change it to use `APP_VERSION`).

- [ ] **Step 10: Update `tests/README.md`**

Add a row in alphabetical position:

```markdown
| `test_release.py` | The three version strings agree, the build tools stay out of the runtime requirements, the release workflow tests before it builds |
```

- [ ] **Step 11: Commit**

```bash
git add RELEASING.md requirements-build.txt requirements.txt app.spec .gitignore .github/workflows/build-and-release.yml .github/dependabot.yml src/config.py version_info.txt sim-cpdlc.iss tests/test_release.py tests/README.md
git commit -m "Carry one version everywhere and test before building a release"
```

---

### Task 2: The About box names a source checkout and is counted as an open dialog

**Files:**
- Modify: `src/gui/dialogs/about_dialog.py`, `src/gui/main_window.py` (`on_about`), `tests/README.md`
- Test: `tests/test_about_dialog.py` (new), `tests/test_main_window.py`

**Interfaces:**
- Produces: `about_dialog.version_label() -> str`, `about_dialog.about_info() -> wx.adv.AboutDialogInfo`; `show_about_dialog(parent)` unchanged in name.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_about_dialog.py`:

```python
"""The About box: the version a user reports, and the copyright year."""

import datetime
import sys

from src.config import APP_VERSION
from src.gui.dialogs import about_dialog


def test_a_source_checkout_says_so(monkeypatch):
    """Bug reports from `python app.py` used to carry a bare version that
    looked like a release (audit M-10)."""
    monkeypatch.delattr(sys, "frozen", raising=False)

    assert about_dialog.version_label() == f"{APP_VERSION} (source)"


def test_a_packaged_build_shows_the_release_number(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert about_dialog.version_label() == APP_VERSION


def test_the_about_box_carries_the_label_and_this_years_copyright(wx_app, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)

    info = about_dialog.about_info()

    assert info.GetVersion() == f"{APP_VERSION} (source)"
    assert info.GetCopyright() == f"Copyright (c) {datetime.date.today().year} Robin Kipp"
```

Append to `tests/test_main_window.py`, after `test_every_dialog_is_counted_while_it_is_open`:

```python
def test_the_about_box_is_counted_while_it_is_open(window, monkeypatch):
    """wx.adv.AboutBox is not a wx.Dialog, so the ShowModal patch above never
    sees it; the update prompt must still wait for it."""
    depths = []
    monkeypatch.setattr(mw, "show_about_dialog", lambda parent: depths.append(window._modal_depth))

    window.on_about(None)

    assert depths == [1]
    assert window._modal_depth == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_about_dialog.py tests/test_main_window.py -k "about"`
Expected: `AttributeError: module 'src.gui.dialogs.about_dialog' has no attribute 'version_label'` (and `about_info`); the window test fails with `depths == [0]`.

- [ ] **Step 3: Rework the About dialog**

Replace `src/gui/dialogs/about_dialog.py` with:

```python
"""About dialog for the Sim-CPDLC application."""

import datetime
import sys

import wx
import wx.adv

from src.config import APP_VERSION, GITHUB_URL


def version_label():
    """The version as the user should report it.

    A packaged build is the release it was built from. A checkout run with
    `python app.py` carries the same number, so it says so: a bug report from
    source is a different thing from one against the installer.

    Returns:
        str: "X.Y.Z" in a packaged build, "X.Y.Z (source)" otherwise
    """
    if getattr(sys, "frozen", False):
        return APP_VERSION
    return f"{APP_VERSION} (source)"


def about_info():
    """Build the information the About box shows.

    Returns:
        wx.adv.AboutDialogInfo: Name, version, description, copyright, website
    """
    info = wx.adv.AboutDialogInfo()
    info.SetName("Sim-CPDLC")
    info.SetVersion(version_label())
    info.SetDescription("A simple CPDLC client for SayIntentions.ai and Hoppie ACARS")
    info.SetCopyright(f"Copyright (c) {datetime.date.today().year} Robin Kipp")
    info.SetWebSite(GITHUB_URL, "View on GitHub")
    return info


def show_about_dialog(parent):
    """Display information about the application.

    Args:
        parent: The parent window
    """
    wx.adv.AboutBox(about_info(), parent)
```

- [ ] **Step 4: Count the About box in the window**

In `src/gui/main_window.py` replace `on_about` with:

```python
    def on_about(self, _):
        """Display information about the application, counted as an open dialog.

        wx.adv.AboutBox is not a wx.Dialog, so it cannot go through
        _show_dialog; the counter is kept by hand so the update prompt waits
        for it like for any other dialog.
        """
        self._modal_depth += 1
        try:
            show_about_dialog(self)
        finally:
            self._modal_depth -= 1
            self._flush_deferred()
```

- [ ] **Step 5: Run the tests and the suite**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_about_dialog.py tests/test_main_window.py`
Expected: all pass.

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 6: Update `tests/README.md`**

```markdown
| `test_about_dialog.py` | The About box: the "(source)" label and the copyright year |
```

- [ ] **Step 7: Commit**

```bash
git add src/gui/dialogs/about_dialog.py src/gui/main_window.py tests/test_about_dialog.py tests/test_main_window.py tests/README.md
git commit -m "Name a source checkout in the About box and count it as an open dialog"
```

---

### Task 3: Logs reach the file, never a logon code

**Files:**
- Modify: `src/utils/simbrief.py:8`, `src/logging_setup.py`, `src/config.py` (`CONFIG_FILE`, `load_config`, `save_config`), `src/model/connection_manager.py:201,207,478`, `src/error_reporting.py`, `tests/README.md`
- Test: `tests/test_logging_setup.py` (new), `tests/test_config.py`, `tests/test_connection_manager.py`, `tests/test_error_reporting.py`

**Interfaces:**
- Produces: nothing new for later tasks. (`config_file_exists()` is added in Task 4.)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_logging_setup.py`:

```python
"""Where log records go: the file always, the console only when there is one."""

import logging
import sys

import pytest

import src.logging_setup as logging_setup
from src.utils import simbrief


@pytest.fixture
def app_logger(monkeypatch, tmp_path):
    """setup_logging() on a fresh logger writing under tmp_path, torn down after."""
    monkeypatch.setattr(logging_setup, "get_user_data_dir", lambda: str(tmp_path))
    logger = logging.getLogger("Sim-CPDLC")
    saved = list(logger.handlers)
    logger.handlers = []
    try:
        yield logger
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers = saved


def test_the_windowed_build_gets_no_console_handler(app_logger, monkeypatch):
    """PyInstaller's console=False leaves sys.stderr as None, and a
    StreamHandler wrapped around None raises on the first record."""
    monkeypatch.setattr(sys, "stderr", None)

    logger = logging_setup.setup_logging()

    assert [type(h).__name__ for h in logger.handlers] == ["RotatingFileHandler"]


def test_a_console_gets_a_console_handler(app_logger):
    logger = logging_setup.setup_logging()

    assert [type(h).__name__ for h in logger.handlers] == ["StreamHandler", "RotatingFileHandler"]


def test_simbrief_logs_under_the_application_logger():
    """Its failure reasons went to an orphan logger with no handlers, so the
    log file only ever said "Failed to fetch SimBrief OFP data" (audit L-6)."""
    assert simbrief.logger.name == "Sim-CPDLC.simbrief"
    assert simbrief.logger.parent is logging.getLogger("Sim-CPDLC")
```

Append to `tests/test_config.py` (add `import logging` and extend the import with `save_config` if missing; `from src import config as config_module`):

```python
def test_the_log_names_the_settings_but_not_their_values(caplog):
    """DEBUG is the level a user is asked to switch on for troubleshooting, and
    it used to print both logon codes (audit L-8)."""
    with caplog.at_level(logging.DEBUG, logger="Sim-CPDLC"):
        assert save_config({**DEFAULT_CONFIG, "hoppie_logon_code": "SECRET42"})
        load_config()

    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "hoppie_logon_code" in joined
    assert "SECRET42" not in joined


def test_saving_creates_the_settings_directory(monkeypatch, tmp_path):
    """The directory used to be created when src.config was imported, on every
    test run and on every machine that merely imported the module."""
    monkeypatch.setattr(config_module, "CONFIG_FILE", str(tmp_path / "fresh" / "config.json"))

    assert save_config(dict(DEFAULT_CONFIG))

    assert (tmp_path / "fresh" / "config.json").is_file()
```

Append to `tests/test_connection_manager.py` (add `import traceback`):

```python
def test_a_transport_failure_keeps_the_logon_code_out_of_the_traceback(logger, monkeypatch):
    """redact() scrubbed the message, but the original requests exception
    stayed attached as __cause__ and traceback formatting printed its URL,
    logon code included (audit L-8)."""
    cm = connected(logger, monkeypatch)
    serving(
        monkeypatch,
        raises=requests.ConnectionError(f"HTTPSConnectionPool: {HOPPIE_API_URL}?logon={LOGON}&from=DLH123"),
    )

    with pytest.raises(HoppieError) as raised:
        cm.send_telex("EDDF", "HELLO")

    rendered = "".join(traceback.format_exception(raised.value))
    assert LOGON not in rendered
    assert raised.value.__cause__ is None
```

Append to `tests/test_error_reporting.py` (add `import logging`):

```python
def test_the_report_redacts_a_logon_code(caplog):
    """The reporter prints the whole traceback, which is where a logon code
    from a requests URL would survive every other redaction."""
    log = logging.getLogger("reporter-under-test")
    reporter = ExceptionReporter(log)
    error = RuntimeError("GET https://www.hoppie.nl/acars/system/connect.html?logon=SECRET42&from=DLH123")

    with caplog.at_level(logging.ERROR, logger=log.name):
        reporter.report(RuntimeError, error, None, "test")

    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "logon=<redacted>" in joined
    assert "SECRET42" not in joined
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_logging_setup.py tests/test_config.py tests/test_connection_manager.py tests/test_error_reporting.py -k "console or simbrief_logs or names_the_settings or creates_the_settings or traceback or redacts"`
Expected: the console test fails with two handlers (or an error from the StreamHandler); the simbrief test fails on the name `src.utils.simbrief`; the config log test finds `SECRET42`; the directory test fails with `FileNotFoundError` from `mkstemp`; the traceback test finds the logon code (via `__cause__`); the reporter test finds `SECRET42`.

- [ ] **Step 3: SimBrief logs under the application logger**

In `src/utils/simbrief.py` replace `logger = logging.getLogger(__name__)` with:

```python
# A child of the application logger, so the reason a fetch failed reaches the
# log file next to the dialog's one-line summary.
logger = logging.getLogger("Sim-CPDLC.simbrief")
```

- [ ] **Step 4: A console handler only where there is a console**

In `src/logging_setup.py` add `import sys` and replace the console-handler block with:

```python
    # Console handler, only where there is a console: the packaged build runs
    # with console=False, which leaves sys.stderr as None.
    if sys.stderr is not None:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_formatter)
        logger.addHandler(console_handler)
```

- [ ] **Step 5: `config.py` logs key names and creates the directory when it writes**

Replace the `CONFIG_FILE` line with:

```python
# Configuration file path. The directory is created when something is written
# there (save_config, the log file), not when this module is imported.
CONFIG_FILE = os.path.join(appdirs.user_data_dir(APP_NAME, APP_AUTHOR), "config.json")
```

In `load_config` change `logger.debug(f"Loaded config: {config}")` to `logger.debug(f"Loaded config with keys: {sorted(config)}")`.

In `save_config` change the start of the `try` block to:

```python
    try:
        config_dir = os.path.dirname(CONFIG_FILE)
        os.makedirs(config_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
```

and `logger.debug(f"Saved config: {config}")` to `logger.debug(f"Saved config with keys: {sorted(config)}")`. (`get_user_data_dir()` keeps its `os.makedirs`; `app.py` and `logging_setup.py` call it at run time.)

- [ ] **Step 6: Redacted errors carry no cause**

In `src/model/connection_manager.py` change the three raises:
- line 201: `raise self._transport_failure(exc, is_send, is_info) from None`
- line 207: `raise error from None`
- line 478: `raise HoppieError(f"{label} request failed: {exc}") from None`

Add above the first one, inside the `except TRANSPORT_ERRORS` block, the comment:

```python
            # from None: the requests exception carries the request URL, logon
            # code included, and traceback formatting prints __cause__ in full.
```

- [ ] **Step 7: The reporter redacts**

In `src/error_reporting.py` add `from src.model.connection_manager import redact` and replace the first two statements of `report()`:

```python
        summary = redact(f"{exc_type.__name__}: {exc_value}")
        details = redact("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
        self.logger.error(f"Unhandled exception in {source}: {summary}\n{details}")
        text = (
            f"An unexpected error occurred:\n\n{summary}\n\n"
            "The details have been written to the log file."
        )
```

- [ ] **Step 8: Run the tests and the suite**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_logging_setup.py tests/test_config.py tests/test_connection_manager.py tests/test_error_reporting.py`
Expected: all pass.

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 9: Update `tests/README.md`**

```markdown
| `test_logging_setup.py` | The log handlers: the file always, the console only when there is one; SimBrief's logger |
```

and change the `test_config.py` row to `Reading, writing and clamping the configuration; what the log says about it`.

- [ ] **Step 10: Commit**

```bash
git add src/utils/simbrief.py src/logging_setup.py src/config.py src/model/connection_manager.py src/error_reporting.py tests/test_logging_setup.py tests/test_config.py tests/test_connection_manager.py tests/test_error_reporting.py tests/README.md
git commit -m "Keep logon codes out of the log and let every record reach the file"
```

---

### Task 4: Stray files, dead code and stale bits

**Files:**
- Delete: `src/utils/latest_simbrief_ofp.json`, `src/utils/test_simbrief.py`
- Create: `tools/simbrief_probe.py`, `tests/test_tools.py`
- Modify: `pytest.ini`, `src/config.py` (`config_file_exists`), `src/gui/main_window.py` (`_check_first_launch`, `get_current_station`, `on_telex`, the `PollingController(...)` call and its imports, the stale menu comment), `src/gui/dialogs/telex_dialog.py`, `src/model/message_manager.py` (`get_weather_key`, `is_acknowledged`, the `sender` hint), `src/gui/message_view.py` (`clear`), `src/model/connection_manager.py` (`message_callback`), `src/controller/polling_controller.py` (`default_poll_interval`), `src/model/cpdlc_session.py:3`, `src/utils/weather_parsing.py` (`extract_atis_letter`), `tests/test_request_dialogs.py`, `tests/test_weather_parsing.py`, `tests/test_connection_manager.py` (unused imports), `tests/README.md`

**Interfaces:**
- Produces: `src.config.config_file_exists() -> bool`; `TelexDialog(parent, recipient)`; `PollingController` no longer takes `default_poll_interval` (positional argument 4 of the window's call goes away; Task 7 relies on this order).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tools.py`:

```python
"""The manual tools under tools/ stay importable and refuse to guess."""

import importlib


def test_the_simbrief_probe_refuses_to_run_without_a_user_id(monkeypatch, capsys):
    """It used to carry a hard-coded id and write the owner's flight plan into
    src/ (audit L-20)."""
    probe = importlib.import_module("tools.simbrief_probe")
    monkeypatch.delenv("SIMBRIEF_USERID", raising=False)

    assert probe.main() == 2
    assert "SIMBRIEF_USERID" in capsys.readouterr().err
```

In `tests/test_request_dialogs.py` change the `telex` fixture to:

```python
@pytest.fixture
def telex(dialog):
    """A Telex dialog opened while logged on to EDDF."""
    return dialog(TelexDialog, "EDDF")
```

In `tests/test_weather_parsing.py` drop the second argument from the four `extract_atis_letter(...)` calls (lines 55, 59, 66, 78), e.g. `extract_atis_letter("EGLL ATIS INFORMATION K RWY 27R") == "K"`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_tools.py tests/test_request_dialogs.py tests/test_weather_parsing.py -k "probe or telex or atis_letter or information"`
Expected: `ModuleNotFoundError: No module named 'tools'`; the telex tests fail with `TypeError: __init__() takes 2 positional arguments but 3 were given`; the ATIS tests still pass (the parameter is optional today).

- [ ] **Step 3: Move the probe and delete the data file**

```bash
git rm -q src/utils/latest_simbrief_ofp.json
git mv src/utils/test_simbrief.py tools/simbrief_probe.py
```

Replace the content of `tools/simbrief_probe.py` with:

```python
#!/usr/bin/env python3
"""Fetch the latest SimBrief flight plan for one user and print its outline.

A manual probe for the SimBrief integration: it talks to the live API and is
not a test. Set SIMBRIEF_USERID in the environment, then run
``python tools/simbrief_probe.py`` from the repository root.
"""

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.simbrief import get_latest_ofp  # noqa: E402


def main():
    """Print the flight, route and aircraft of the latest OFP.

    Returns:
        int: 0 on success, 1 when SimBrief returned nothing, 2 without a user id
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    user_id = os.environ.get("SIMBRIEF_USERID", "").strip()
    if not user_id:
        print("Set SIMBRIEF_USERID to your SimBrief user id first.", file=sys.stderr)
        return 2

    ofp = get_latest_ofp(user_id)
    if not ofp:
        print("SimBrief returned no flight plan; see the log lines above.", file=sys.stderr)
        return 1

    general = ofp.get("general", {})
    origin = ofp.get("origin", {})
    destination = ofp.get("destination", {})
    print(f"Flight:   {general.get('icao_airline', '')}{general.get('flight_number', '')}")
    print(f"Route:    {origin.get('icao_code', '')} -> {destination.get('icao_code', '')}")
    print(f"Aircraft: {general.get('aircraft_icao', '')} {general.get('aircraft_name', '')}".rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

In `pytest.ini` replace the first comment with:

```ini
# Scoped to tests/ deliberately: tools/ holds manual scripts that talk to live
# services.
```

- [ ] **Step 4: Remove the dead code**

- `src/model/message_manager.py`: delete `get_weather_key` and `is_acknowledged`; change `add_custom_message(self, text: str, sender: str = None)` to `sender: Optional[str] = None`.
- `src/gui/message_view.py`: delete `clear` (its `_fit_columns()` call goes with it).
- `src/model/connection_manager.py`: `def __init__(self, logger):` — remove the `message_callback` parameter, its docstring line and `self.message_callback = message_callback`.
- `src/controller/polling_controller.py`: remove the `default_poll_interval=60000` parameter, its docstring entry and `self.default_poll_interval = default_poll_interval`.
- `src/gui/main_window.py`: in the `PollingController(...)` call delete the `DEFAULT_POLL_INTERVAL,` argument line (the call becomes `logger, self.connection_manager, self._on_message_received, ACTIVE_POLL_INTERVAL, INACTIVITY_TIMEOUT, link_callback=..., ...`), and remove `DEFAULT_POLL_INTERVAL` from the `src.config` import. In `src/config.py` delete the `DEFAULT_POLL_INTERVAL = 60000` line (the band's comment stays).
- `src/model/cpdlc_session.py`: delete `import logging`.
- `src/gui/main_window.py`: delete the comment line `# Always enable both logon and logoff menu items`.
- `src/utils/weather_parsing.py`: `def extract_atis_letter(text):`, and drop the `, icao` argument from its two callers (lines 199 and 226); keep the docstring's explanation of why the airport code is not used as a marker.
- `tests/test_connection_manager.py`: delete the unused `import logging`, and `HoppieConnector` and `PollResult` from the imports.

- [ ] **Step 5: `_check_first_launch` without local imports, and the Telex recipient as an argument**

`src/config.py`, after `CONFIG_FILE`:

```python
def config_file_exists():
    """Whether a configuration file has been written yet (False on first launch)."""
    return os.path.exists(CONFIG_FILE)
```

`src/gui/main_window.py`: add `DEFAULT_CONFIG` and `config_file_exists` to the `src.config` import; replace the start of `_check_first_launch` up to `self.logger.info("First launch detected - creating config file")` with:

```python
    def _check_first_launch(self):
        """Check if this is the first launch and prompt for settings if needed."""
        if config_file_exists():
            return

        self.logger.info("First launch detected - creating config file")
```

and dedent the rest of the method's body by one level (the `if not config_file_exists:` wrapper is gone). Delete `get_current_station` and change `on_telex` to `dlg = TelexDialog(self, self.cpdlc_session.get_current_station())`.

`src/gui/dialogs/telex_dialog.py`: `def __init__(self, parent, recipient):` with the docstring `recipient: The station to address by default; the current station, or "" when not logged on`, and `self.recipient_text.SetValue(recipient)`.

- [ ] **Step 6: Verify by grep, then run the suite**

Run these and expect no output from each:

```bash
grep -rn "get_weather_key\|is_acknowledged\|message_callback=\|default_poll_interval\|DEFAULT_POLL_INTERVAL\|get_current_station()" src/gui/main_window.py src/model/message_manager.py src/model/connection_manager.py src/controller/polling_controller.py src/config.py | grep -v "cpdlc_session.get_current_station\|session.get_current_station\|self.message_callback\|message_callback: Callback\|message_callback = message_callback\|message_callback=None"
grep -rn "Always enable both\|latest_simbrief_ofp\|test_simbrief" src tests pytest.ini
grep -rn "def clear" src/gui/message_view.py
```

(`PollingController` keeps its own `message_callback`; only `ConnectionManager`'s goes.)

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 7: Update `tests/README.md`**

```markdown
| `test_tools.py` | The manual SimBrief probe refuses to run without a user id |
```

- [ ] **Step 8: Commit**

```bash
git add -A src/utils tools pytest.ini src/config.py src/gui/main_window.py src/gui/dialogs/telex_dialog.py src/model/message_manager.py src/gui/message_view.py src/model/connection_manager.py src/controller/polling_controller.py src/model/cpdlc_session.py src/utils/weather_parsing.py tests/test_tools.py tests/test_request_dialogs.py tests/test_weather_parsing.py tests/test_connection_manager.py tests/README.md
git commit -m "Remove the stray SimBrief files, dead code and stale comments"
```

---

### Task 5: One logon gate for every request

**Files:**
- Modify: `src/gui/main_window.py` (`_require_logon` new; `on_logoff`, `on_altitude_change`, `on_direct_request`, `on_speed_request`, `on_when_can_we_expect`)
- Test: `tests/test_main_window.py`

**Interfaces:**
- Produces: `MainWindow._require_logon(action) -> bool`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_main_window.py`:

```python
# --- the logon gate ---------------------------------------------------------------


@pytest.mark.parametrize(
    "handler, action",
    [
        ("on_logoff", "log off"),
        ("on_altitude_change", "request an altitude change"),
        ("on_direct_request", "request a direct routing"),
        ("on_speed_request", "request a speed change"),
        ("on_when_can_we_expect", "send a when-can-we-expect inquiry"),
    ],
)
def test_a_request_without_a_logon_is_refused_with_one_message(window, message_boxes, handler, action):
    """Five handlers hand-rolled the same box with three different wordings."""
    window.connection_manager = FakeConnectionManager()
    window.cpdlc_session.connection_manager = window.connection_manager

    getattr(window, handler)(None)

    assert message_boxes.calls == [
        (f"You must be logged on to a station to {action}.", "Not Logged On", wx.OK | wx.ICON_INFORMATION)
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_main_window.py -k without_a_logon`
Expected: the logoff case fails on the wording (`"You are not currently logged on to any station."`), the direct, speed and when-can-we cases on `"send a request"`.

- [ ] **Step 3: Add the gate and use it**

In `src/gui/main_window.py` add after `_require_connection`:

```python
    def _require_logon(self, action):
        """Check we are logged on to a station, telling the user if we are not.

        Args:
            action: What the user was trying to do, for the message text

        Returns:
            bool: True if logged on
        """
        if self.cpdlc_session.is_logged_on():
            return True

        self._message_box(
            f"You must be logged on to a station to {action}.",
            "Not Logged On",
            wx.OK | wx.ICON_INFORMATION,
        )
        return False
```

Replace each hand-rolled block:

`on_logoff`: the `if not self.cpdlc_session.is_logged_on(): self._message_box("You are not currently logged on to any station.", ...) return` block becomes

```python
        if not self._require_logon("log off"):
            return
```

`on_altitude_change`:

```python
        if not self._require_connection("request an altitude change"):
            return
        if not self._require_logon("request an altitude change"):
            return
```

`on_direct_request`:

```python
        if not self._require_connection("request a direct routing"):
            return
        if not self._require_logon("request a direct routing"):
            return
```

`on_speed_request`:

```python
        if not self._require_connection("request a speed change"):
            return
        if not self._require_logon("request a speed change"):
            return
```

`on_when_can_we_expect`:

```python
        if not self._require_connection("send a when-can-we-expect inquiry"):
            return
        if not self._require_logon("send a when-can-we-expect inquiry"):
            return
```

Delete the now-unused `# Check if connected and logged on` comments. `on_telex` keeps only its connection gate (a telex goes to any station).

Run `grep -n '"Not Logged On"' src/gui/main_window.py` — expected: exactly one hit, inside `_require_logon`.

- [ ] **Step 4: Run the tests and the suite**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_main_window.py`
Expected: all pass.

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all pass (if a test elsewhere asserted the old `"send a request"` wording of the connection gate, update it to the new action text).

- [ ] **Step 5: Commit**

```bash
git add src/gui/main_window.py tests/test_main_window.py
git commit -m "Gate every station request through one logon check"
```

---

### Task 6: The docs describe the client as it now behaves

**Files:**
- Modify: `README.md`, `tests/README.md`, `src/utils/weather_parsing.py:112-117` (the `format_report_text` docstring)

**Interfaces:** none.

- [ ] **Step 1: README.md**

Make these edits (line numbers from the current file):

Line 20, the Features bullet:

```markdown
- **Resilient link**: rides out network outages, announces a lost and a restored link, and keeps polling
```

Line 30: `- Python 3.12 or higher`

Line 69 (Logging On, step 2): ``2. Enter the four-letter code of the ATC station (e.g., `KUSA` for en route CPDLC within the US)``

Lines 84-91 (the altitude section) become:

```markdown
### Requesting Altitude Changes

1. Go to `Requests > Altitude change`
2. Enter the flight level as two or three digits without `FL` (`350` for FL350, `90` for FL090)
3. Optionally give a reason: weather or aircraft performance
4. Click OK to send the request

`Requests > Direct to`, `Requests > Speed change` and `Requests > When can we
expect` work the same way. Each dialog says what it accepts and only enables OK
for a value the network will take.
```

Lines 93-99 (Telex) become:

```markdown
### Sending TELEX Messages

1. Go to `Requests > Telex message`
2. Enter:
   - Recipient: a station name or callsign of 3 to 8 letters or digits (your current station is filled in)
   - Message text: up to 220 plain-ASCII characters; the dialog counts them as you type
3. Click OK to send the message
```

Lines 109-110 (after the weather steps) become:

```markdown
The report is added to the message list without the notification sound: you
asked for it, so there is nothing to announce. Automatic updates (below) do
play it, because they arrive unprompted.
```

Insert before `## Running the Tests`:

```markdown
### Network Behaviour

All network traffic runs on one background thread, so the window never freezes
while a message is on its way. Messages go out one at a time, five seconds
apart, which is what the networks ask for; the status bar reads `Sending ...`
while a message is queued and `Sent ...` once it has gone. On exit the client
waits up to five seconds for anything still queued, such as the logoff message.

A poll that fails is retried. After three failures in a row the link counts as
lost: the status bar and a `SYSTEM` message say so and the notification sound
plays. Polling continues at growing intervals (20 seconds, then 1, 2 and 5
minutes) until a poll succeeds, and `Connection restored` is announced the same
way. Polling only stops on its own when the server rejects your logon code,
which no retry can fix.

A checkout run with `python app.py` shows its version as `X.Y.Z (source)` in
`File > About` and never checks for updates automatically; packaged builds do,
unless you switch it off in `File > Settings`.
```

- [ ] **Step 2: tests/README.md and the weather_parsing docstring**

In `tests/README.md` lines 26-28 change `and one worker test starts a thread on purpose` to `and two worker tests start a thread on purpose` after confirming the count: `grep -c "NetworkWorker(logger, dispatch=inline" tests/test_network_worker.py` (the constructions without `start_thread=False`) — if the count differs from two, write the number you found.

In `src/utils/weather_parsing.py` change the `format_report_text` docstring's second sentence to:

```python
    Hoppie separates the lines of an information report with "@", which a
    screen reader announces as the word "at" if it is left in place. This is
    deliberately not message_formatting.format_message_text: that helper
    treats "@" as the field separator of a CPDLC element and strips
    underscores, conventions that would corrupt a weather report.
```

- [ ] **Step 3: Check and commit**

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all pass (docs only).

Run `grep -n "3.7\|Climb or descent\|sound plays, just\|Automatic Reconnection\|N/A" README.md src/utils/weather_parsing.py` — expected: no output.

```bash
git add README.md tests/README.md src/utils/weather_parsing.py
git commit -m "Describe the client as it now behaves"
```

---

### Task 7: A required worker, and two accessibility conventions

**Files:**
- Modify: `src/model/cpdlc_session.py` (`__init__`), `src/controller/polling_controller.py` (`__init__`), `src/model/weather_monitor.py` (`__init__`), `src/utils/update_checker.py` (`__init__`), `src/model/network_worker.py` (`run_detached`), `src/gui/dialogs/altitude_change_dialog.py`, `direct_request_dialog.py`, `speed_request_dialog.py`, `when_can_we_dialog.py`, `connect_dialog.py`, `tests/test_polling_controller.py:16-17`, `tests/README.md`
- Test: `tests/test_network_worker.py`, `tests/test_request_dialogs.py`, `tests/test_dialogs.py`

**Interfaces:**
- Produces: `CpdlcSession(logger, connection_manager, *, worker, clock=time.monotonic)`, `PollingController(logger, connection_manager, message_callback=None, active_poll_interval=20000, inactivity_timeout=300000, poll_interval_range=None, link_callback=None, unreadable_callback=None, tick_callback=None, *, worker)`, `WeatherMonitor(logger, connection_manager, on_update=None, on_error=None, interval_ms=300000, *, worker)`, `UpdateChecker(logger, worker)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_network_worker.py` (add the imports it needs: `from src.model.cpdlc_session import CpdlcSession`, `from src.controller.polling_controller import PollingController`, `from src.model.weather_monitor import WeatherMonitor`, `from src.utils.update_checker import UpdateChecker`, `from tests.support import FakeConnectionManager`, and `inline_worker` if not already imported):

```python
# --- the worker is not optional ---------------------------------------------------


@pytest.mark.parametrize(
    "build",
    [
        lambda logger: CpdlcSession(logger, FakeConnectionManager()),
        lambda logger: PollingController(logger, FakeConnectionManager()),
        lambda logger: WeatherMonitor(logger, FakeConnectionManager()),
        lambda logger: UpdateChecker(logger),
    ],
    ids=["session", "poller", "weather", "updates"],
)
def test_the_network_collaborators_insist_on_a_worker(logger, build):
    """A default of None used to fail on the first job submitted, far from the
    constructor that forgot the worker."""
    with pytest.raises(TypeError):
        build(logger)


def test_a_paced_kind_cannot_be_run_detached(logger):
    """Detached jobs bypass the spacing; a send or an inforeq run that way
    would reach the server out of turn."""
    worker = inline_worker(logger)

    with pytest.raises(ValueError):
        worker.run_detached("send", lambda: None)
```

Append to `tests/test_request_dialogs.py`:

```python
# --- helper texts ---------------------------------------------------------------


@pytest.mark.parametrize(
    "factory",
    [AltitudeChangeDialog, DirectRequestDialog, SpeedRequestDialog, WhenCanWeDialog],
    ids=["altitude", "direct", "speed", "when-can-we"],
)
def test_helper_text_uses_the_system_grey_so_high_contrast_themes_apply(dialog, factory):
    built = dialog(factory)

    assert built.helper_text.GetForegroundColour() == wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT)
```

Append to `tests/test_dialogs.py`:

```python
def test_the_network_choice_is_labelled_as_a_group(dialog):
    """A RadioBox with an empty label and a StaticText beside it reads as two
    unrelated things to a screen reader."""
    connect = dialog(ConnectDialog, fetch_simbrief=RecordingFetch(configured=False))

    assert connect.network_radio_box.GetLabel() == "Network"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_network_worker.py tests/test_request_dialogs.py tests/test_dialogs.py -k "insist or paced_kind or system_grey or labelled_as_a_group"`
Expected: the four constructor cases fail with `DID NOT RAISE`; the detached test fails with `DID NOT RAISE`; the altitude case fails with `AttributeError: 'AltitudeChangeDialog' object has no attribute 'helper_text'` and the others on the colour; the RadioBox test fails with `'' != 'Network'`.

- [ ] **Step 3: Make the worker required**

- `src/model/cpdlc_session.py`: `def __init__(self, logger, connection_manager: ConnectionManager, *, worker, clock: Callable[[], float] = time.monotonic):` with the docstring entry `worker: The NetworkWorker that transmits the frames (required)`.
- `src/controller/polling_controller.py`: move `worker` to the end as `*, worker` (after `tick_callback=None`), docstring `worker: The NetworkWorker that runs the polls (required)`.
- `src/model/weather_monitor.py`: `def __init__(self, logger, connection_manager, on_update=None, on_error=None, interval_ms=300000, *, worker):`.
- `src/utils/update_checker.py`: `def __init__(self, logger, worker):` and drop any `if worker is None` / `if logger is None` fallbacks the class carries.
- `tests/test_polling_controller.py`: `def controller(logger): return PollingController(logger, connection_manager=None, worker=inline_worker(logger))`.

Run `grep -rn "PollingController(\|CpdlcSession(\|WeatherMonitor(\|UpdateChecker(" src tests --include=*.py | grep -v "class \|worker"` — expected: no output (every construction passes a worker).

- [ ] **Step 4: `run_detached` refuses a paced kind**

In `src/model/network_worker.py`, at the top of `run_detached`:

```python
        if kind in self._spacing:
            raise ValueError(f"{kind} jobs are paced; queue them with submit()")
```

and add to its docstring: `Raises: ValueError: For a kind that is paced (send, inforeq); pacing only works inside the queue.`

- [ ] **Step 5: The two accessibility conventions**

In `altitude_change_dialog.py`, `direct_request_dialog.py`, `speed_request_dialog.py` and `when_can_we_dialog.py` replace `SetForegroundColour(wx.Colour(100, 100, 100))` (with or without its comment) by `SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))`; in `altitude_change_dialog.py` the helper becomes `self.helper_text` (three references: creation, colour, `vbox.Add`).

In `connect_dialog.py` delete the two lines creating and adding `network_label` (`wx.StaticText(self, label="Select Network:")` and its `vbox.Add`), and give the box its label: `label="Network",`.

- [ ] **Step 6: Run the tests and the suite**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_network_worker.py tests/test_request_dialogs.py tests/test_dialogs.py`
Expected: all pass.

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 7: Update `tests/README.md`**

Change the `test_network_worker.py` row to `The network worker: ordering, generations, pacing, failure capture, shutdown; the collaborators that require one`.

- [ ] **Step 8: Commit**

```bash
git add src/model/cpdlc_session.py src/controller/polling_controller.py src/model/weather_monitor.py src/utils/update_checker.py src/model/network_worker.py src/gui/dialogs/altitude_change_dialog.py src/gui/dialogs/direct_request_dialog.py src/gui/dialogs/speed_request_dialog.py src/gui/dialogs/when_can_we_dialog.py src/gui/dialogs/connect_dialog.py tests/test_polling_controller.py tests/test_network_worker.py tests/test_request_dialogs.py tests/test_dialogs.py tests/README.md
git commit -m "Require the network worker and follow the system colours and group labels"
```

---

## Self-review

- **Spec coverage:** Version: RELEASING.md, tag check, test job, "(source)", copyright year (Tasks 1, 2). Dependencies: `requirements-build.txt`, `SimConnect==0.4.26`, `app.spec` SystemExit, `.gitignore`, dependabot github-actions (Task 1). Docs: Python 3.12, altitude section, sound sentence, reconnection paragraph, tests pointer kept, `app.py` docstring already names both networks (Task 6). Hygiene: the JSON and the probe (Task 4); unused imports (`cpdlc_session.py` `logging`; `main_window.py` and `polling_controller.py` carry none today, verified by an AST scan) (Task 4); `get_weather_key`, `ConnectionManager.message_callback`, `default_poll_interval`, `get_current_station` with `TelexDialog(parent, recipient)`, the local imports in `_check_first_launch` (Task 4); `send_logoff_message` is already gone (package 3); `_require_logon` (Task 5); `_send_request` already exists behind the four request senders (package 4); SimBrief logger, console handler, key-name logging, `from None`, `Optional[str]`, grey helper texts, RadioBox "Network" (Tasks 3, 4, 7). Follow-ups from earlier reviews: import-time `makedirs` (Task 3), README thread count (Task 6), About counted (Task 2), `is_acknowledged` and `MessageView.clear` (Task 4), `run_detached` guard and required workers (Task 7), README worker and link paragraphs (Task 6), `format_report_text` docstring (Task 6), `extract_atis_letter` (Task 4).
- **Placeholders:** `a2fc377` and `518` in Global Constraints are filled in when this plan is committed on the branch; nothing else.
- **Type consistency:** `config_file_exists()` (Task 4) is used by the window in the same task; `TelexDialog(parent, recipient)` in Task 4's dialog, window and test; the `PollingController` argument order after Task 4 is the one Task 7 restates; `version_label()`/`about_info()` in Task 2's module and tests; `_require_logon(action)` in Task 5's helper and test table.
