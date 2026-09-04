"""Update checker for the Sim-CPDLC application.

The lookup runs on the network worker and reports an outcome; the window owns
every prompt, so an "update available" message waits for any open dialog and
never closes the application from under one (audit M-5).
"""

import functools
from dataclasses import dataclass
from typing import Optional

import requests
from packaging import version

from src.config import APP_VERSION, GITHUB_URL
from src.model.network_worker import PRIORITY_INFO


@dataclass
class UpdateOutcome:
    """What a check found.

    Attributes:
        latest: The latest released version, or None when it could not be read
        url: The release page, or None
        newer: True when latest is newer than the running version
        error: The failure text when the lookup failed, else None
    """

    latest: Optional[str] = None
    url: Optional[str] = None
    newer: bool = False
    error: Optional[str] = None


class UpdateChecker:
    """Looks up the latest release on GitHub, off the GUI thread."""

    def __init__(self, logger, worker):
        """Initialize the update checker.

        Args:
            logger: Application logger
            worker: The NetworkWorker that runs the lookup
        """
        self.logger = logger
        self.worker = worker
        self.current_version = APP_VERSION

    def check(self, on_done):
        """Fetch the latest release and report it.

        Args:
            on_done: Callable(UpdateOutcome), run on the GUI thread
        """
        self.worker.submit(
            "update",
            self._get_latest_version,
            functools.partial(self._report, on_done),
            PRIORITY_INFO,
        )

    def _report(self, on_done, result):
        """Turn the worker's result into an outcome. Runs on the GUI thread."""
        if not result.ok:
            self.logger.error(f"Error checking for updates: {result.error}")
            on_done(UpdateOutcome(error=result.error))
            return

        latest, url = result.value
        on_done(UpdateOutcome(latest=latest, url=url, newer=self._is_newer_version(latest)))

    def _get_latest_version(self):
        """Read the latest release tag from GitHub. Runs on the worker.

        Returns:
            tuple: (version_string, release_url)

        Raises:
            Whatever requests raises; the worker turns it into a failed result.
        """
        # GITHUB_URL is https://github.com/<user>/<repo>
        parts = GITHUB_URL.strip("/").split("/")
        api_url = f"https://api.github.com/repos/{parts[-2]}/{parts[-1]}/releases/latest"
        self.logger.debug(f"Checking for updates at: {api_url}")

        response = requests.get(api_url, timeout=5)
        response.raise_for_status()
        data = response.json()
        return data.get("tag_name", "").lstrip("v"), data.get("html_url", "")

    def _is_newer_version(self, latest_version):
        """Check if latest_version is newer than the running version."""
        if not latest_version:
            return False
        try:
            return version.parse(latest_version) > version.parse(self.current_version)
        except Exception as exc:
            self.logger.error(f"Error comparing versions: {exc}")
            return False
