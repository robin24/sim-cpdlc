"""SimBrief API integration for fetching Operational Flight Plan (OFP) data."""

import requests
import json
import logging
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)


class SimBriefAPI:
    """Interface for the SimBrief API to fetch flight plan data."""

    BASE_URL = "https://www.simbrief.com/api/xml.fetcher.php"

    @staticmethod
    def fetch_ofp(user_id: str, format: str = "json") -> Optional[Dict[str, Any]]:
        """Fetch the latest OFP data for a given SimBrief user ID."""
        # Validate user_id
        if not user_id or not isinstance(user_id, str):
            logger.error("Invalid SimBrief user ID")
            return None

        params = {"userid": user_id, "json": 1 if format.lower() == "json" else 0}

        try:
            logger.info(f"Fetching SimBrief OFP for user ID: {user_id}")
            response = requests.get(
                SimBriefAPI.BASE_URL,
                params=params,
                timeout=10,  # Add timeout to prevent hanging
            )
            response.raise_for_status()  # Raise exception for HTTP errors

            if format.lower() == "json":
                data = response.json()
                # Validate response contains expected data
                if not data or not isinstance(data, dict):
                    logger.error("Invalid response format from SimBrief API")
                    return None
                return data
            else:
                # Return XML as string if not requesting JSON
                return response.text

        except requests.exceptions.Timeout:
            logger.error("Timeout while fetching SimBrief OFP")
            return None
        except requests.exceptions.ConnectionError:
            logger.error("Connection error while fetching SimBrief OFP")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching SimBrief OFP: {str(e)}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding SimBrief JSON response: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching SimBrief OFP: {str(e)}")
            return None


def get_latest_ofp(user_id: str) -> Optional[Dict[str, Any]]:
    """Fetch the latest OFP for a SimBrief user."""
    return SimBriefAPI.fetch_ofp(user_id)
