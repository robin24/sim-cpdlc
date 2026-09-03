"""Configuration settings and constants for the Sim-CPDLC application."""

import os
import json
import logging
import tempfile
import appdirs

# Application information
APP_NAME = "Sim-CPDLC"
APP_AUTHOR = "Sim-CPDLC"
GITHUB_URL = "https://github.com/robin24/sim-cpdlc"

# Application version - this will be updated by update_version.py
APP_VERSION = "0.1.0"


# Get user data directory
def get_user_data_dir():
    """Get the OS-specific user data directory for this application."""
    data_dir = appdirs.user_data_dir(APP_NAME, APP_AUTHOR)
    # Ensure directory exists
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


# Configuration file path
CONFIG_FILE = os.path.join(get_user_data_dir(), "config.json")

# Default configuration
DEFAULT_CONFIG = {
    "sayintentions_logon_code": "",
    "hoppie_logon_code": "",
    "simbrief_userid": "",
    "auto_check_updates": True,  # Enable automatic update checks by default
    "auto_tune_com1": True,  # Auto-tune COM1 standby on CONTACT/MONITOR messages
    "weather_update_interval": 5,  # Minutes between automatic weather re-checks
}


def load_config():
    """Load application configuration from file or return defaults."""
    logger = logging.getLogger("Sim-CPDLC")

    if not os.path.exists(CONFIG_FILE):
        logger.info(f"Config file not found at {CONFIG_FILE}, using defaults")
        return DEFAULT_CONFIG.copy()

    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
            logger.debug(f"Loaded config: {config}")

            # Validate required fields exist, add any missing ones
            for key, default_value in DEFAULT_CONFIG.items():
                if key not in config:
                    logger.warning(f"Missing config key '{key}', using default value")
                    config[key] = default_value

            return config
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in config file: {e}")
        return DEFAULT_CONFIG.copy()
    except IOError as e:
        logger.error(f"Error reading config file: {e}")
        return DEFAULT_CONFIG.copy()


def save_config(config):
    """Save configuration to file and return success status."""
    logger = logging.getLogger("Sim-CPDLC")

    # Validate config is a dictionary
    if not isinstance(config, dict):
        logger.error("Invalid config format: must be a dictionary")
        return False

    try:
        config_dir = os.path.dirname(CONFIG_FILE)
        fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(config, f, indent=2)
            os.replace(tmp_path, CONFIG_FILE)
            logger.debug(f"Saved config: {config}")
        except BaseException:
            os.unlink(tmp_path)
            raise
        return True
    except IOError as e:
        logger.error(f"Error writing config file: {e}")
        return False


# API URLs
# HTTPS is required: the logon code travels as a query parameter on every
# request, so plain HTTP would expose it to anyone on the same network.
SAYINTENTIONS_API_URL = "https://acars.sayintentions.ai/acars/system/connect.html"
HOPPIE_API_URL = "https://www.hoppie.nl/acars/system/connect.html"

# Polling configuration (in milliseconds).
# Hoppie asks for a poll "once between every 45 and 75 seconds, randomly timed
# so that the average server load is stable", rising to once per 20 seconds
# while a reply is expected. Each idle poll is randomised within this band.
MIN_POLL_INTERVAL = 45000  # 45 seconds
MAX_POLL_INTERVAL = 75000  # 75 seconds
DEFAULT_POLL_INTERVAL = 60000  # 60 seconds, the average of the band above
ACTIVE_POLL_INTERVAL = 20000  # 20 seconds, the fastest rate Hoppie permits
INACTIVITY_TIMEOUT = 300000  # 5 minutes

# Consecutive failed polls before the link counts as lost
MAX_CONNECTION_FAILURES = 3

# Once the link is lost (MAX_CONNECTION_FAILURES consecutive failed polls) the
# next polls wait these long, in order, staying on the last value until a poll
# succeeds. Polling never stops on its own: a six-minute outage must not end
# the session.
LINK_BACKOFF_MS = (20000, 60000, 120000, 300000)

# SayIntentions answers "rate_limit" to a second message sent within a few
# seconds of the first. A rate-limited acknowledgement is retried once after
# this delay.
RATE_LIMIT_RETRY_MS = 5000

# After a HANDOVER the station that handed the aircraft over may still send
# a WILCO-required instruction (typically the CONTACT frequency); the log
# shows this in 22 of 163 handovers. Its uplinks stay answerable this long.
PREVIOUS_STATION_WINDOW_SECONDS = 600

# A REQUEST LOGON nobody answers is given up on after this long, and the
# pilot is told.
PENDING_LOGON_TIMEOUT_SECONDS = 600

# Automatic weather updates. The interval is a re-request on a timer rather
# than a push from the network, so keep it gentle on the ACARS servers.
DEFAULT_WEATHER_INTERVAL_MINUTES = 5
MIN_WEATHER_INTERVAL_MINUTES = 1
MAX_WEATHER_INTERVAL_MINUTES = 60


def weather_interval_minutes(config):
    """Return the automatic weather interval, clamped to a sane range.

    load_config() fills in missing keys but validates neither type nor range,
    so a hand-edited or downgrade-written file reaches the application as-is.
    The settings dialog enforces the bounds through its SpinCtrl, which a user
    who never opens it never goes through: zero would start a wx.Timer firing
    as fast as the event loop allows, and a string would make the
    minutes-to-milliseconds multiply build a 60000-character string.

    Args:
        config: The loaded configuration mapping

    Returns:
        int: Minutes between checks, within MIN_ and MAX_WEATHER_INTERVAL_MINUTES
    """
    minutes = config.get("weather_update_interval", DEFAULT_WEATHER_INTERVAL_MINUTES)

    if not isinstance(minutes, int) or isinstance(minutes, bool):
        return DEFAULT_WEATHER_INTERVAL_MINUTES

    return max(MIN_WEATHER_INTERVAL_MINUTES, min(MAX_WEATHER_INTERVAL_MINUTES, minutes))

# Network timeout in seconds, applied to every outbound ACARS request.
# hoppie_connector sets no timeout of its own, so without this a server that
# accepts the connection and then stops responding would block forever.
NETWORK_TIMEOUT = 15

# Sound file path
MESSAGE_SOUND_FILENAME = "message.wav"
