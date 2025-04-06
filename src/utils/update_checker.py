"""Update checker for the Sim-CPDLC application."""

import logging
import threading
import webbrowser
import wx
import requests
from packaging import version

from src.config import APP_VERSION, GITHUB_URL


class UpdateChecker:
    """Check for updates to the application."""

    def __init__(self, parent, logger=None):
        """Initialize the update checker.

        Args:
            parent: The parent window for dialogs
            logger: Optional logger instance
        """
        self.parent = parent
        self.logger = logger or logging.getLogger("Sim-CPDLC")
        self.current_version = APP_VERSION

    def check_for_updates(self, auto_check=True):
        """Check for updates to the application.

        Args:
            auto_check: If True, check in background thread and only show dialog if update available
        """
        if auto_check:
            # Run in background thread to avoid blocking the UI
            thread = threading.Thread(target=self._check_in_background)
            thread.daemon = True
            thread.start()
        else:
            # Run synchronously and show result dialog
            self._check_and_show_result()

    def _check_in_background(self):
        """Check for updates in a background thread."""
        try:
            latest_version, release_url = self._get_latest_version()
            if latest_version and self._is_newer_version(latest_version):
                # Schedule dialog on the main thread
                wx.CallAfter(self._show_update_dialog, latest_version, release_url)
        except Exception as e:
            self.logger.error(f"Error checking for updates: {e}")

    def _check_and_show_result(self):
        """Check for updates and show result dialog."""
        try:
            latest_version, release_url = self._get_latest_version()
            if latest_version:
                if self._is_newer_version(latest_version):
                    self._show_update_dialog(latest_version, release_url)
                else:
                    wx.MessageBox(
                        f"You are running the latest version ({self.current_version}).",
                        "No Updates Available",
                        wx.OK | wx.ICON_INFORMATION,
                    )
            else:
                wx.MessageBox(
                    "Could not retrieve version information from GitHub.",
                    "Update Check Failed",
                    wx.OK | wx.ICON_ERROR,
                )
        except Exception as e:
            self.logger.error(f"Error checking for updates: {e}")
            wx.MessageBox(
                f"Error checking for updates: {e}",
                "Update Check Failed",
                wx.OK | wx.ICON_ERROR,
            )

    def _get_latest_version(self):
        """Get the latest version from GitHub.

        Returns:
            tuple: (version_string, release_url) or (None, None) if error
        """
        try:
            # Extract username and repo name from GitHub URL
            # URL format: https://github.com/username/repo
            parts = GITHUB_URL.strip("/").split("/")
            username = parts[-2]
            repo = parts[-1]

            # Get latest release from GitHub API
            api_url = f"https://api.github.com/repos/{username}/{repo}/releases/latest"
            self.logger.debug(f"Checking for updates at: {api_url}")

            response = requests.get(api_url, timeout=5)
            response.raise_for_status()

            data = response.json()
            tag_name = data.get("tag_name", "")
            html_url = data.get("html_url", "")

            # Remove 'v' prefix if present
            version_str = tag_name.lstrip("v")

            return version_str, html_url
        except Exception as e:
            self.logger.error(f"Error getting latest version: {e}")
            return None, None

    def _is_newer_version(self, latest_version):
        """Check if the latest version is newer than the current version.

        Args:
            latest_version: Version string to compare with current version

        Returns:
            bool: True if latest_version is newer
        """
        try:
            return version.parse(latest_version) > version.parse(self.current_version)
        except Exception as e:
            self.logger.error(f"Error comparing versions: {e}")
            return False

    def _show_update_dialog(self, latest_version, release_url):
        """Show update dialog and handle user response.

        Args:
            latest_version: The latest version string
            release_url: URL to the latest release
        """
        result = wx.MessageBox(
            f"A new version of Sim-CPDLC is available!\n\n"
            f"Current version: {self.current_version}\n"
            f"Latest version: {latest_version}\n\n"
            f"Would you like to download the update now?",
            "Update Available",
            wx.YES_NO | wx.ICON_INFORMATION,
        )

        if result == wx.YES:
            self.logger.info(f"User chose to update to version {latest_version}")
            try:
                # Open release page in browser
                webbrowser.open(release_url)

                # Close the application
                wx.CallAfter(self.parent.Close)
            except Exception as e:
                self.logger.error(f"Error opening browser: {e}")
                wx.MessageBox(
                    f"Error opening browser: {e}\n\n"
                    f"Please visit {release_url} manually to download the update.",
                    "Error",
                    wx.OK | wx.ICON_ERROR,
                )
