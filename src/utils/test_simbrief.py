"""Test script for SimBrief API integration."""

import sys
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Add parent directory to path to allow imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from src.utils.simbrief import get_latest_ofp
import json


def test_simbrief_api():
    """Test SimBrief API with sample user ID and display flight information."""
    try:
        # Using the provided test ID
        user_id = "189007"

        logging.info(f"Fetching SimBrief OFP for user ID: {user_id}")
        ofp_data = get_latest_ofp(user_id)

        if ofp_data:
            # Print some key information from the OFP
            general = ofp_data.get("general", {})
            origin = ofp_data.get("origin", {})
            destination = ofp_data.get("destination", {})

            logging.info("\nFlight Information:")
            logging.info(
                f"Flight: {general.get('icao_airline', '')}{general.get('flight_number', '')}"
            )
            logging.info(
                f"Route: {origin.get('icao_code', '')} → {destination.get('icao_code', '')}"
            )
            logging.info(
                f"Aircraft: {general.get('aircraft_icao', '')} - {general.get('aircraft_name', '')}"
            )

            # Save the full OFP to a file for inspection
            output_file = os.path.join(
                os.path.dirname(__file__), "latest_simbrief_ofp.json"
            )
            with open(output_file, "w") as f:
                json.dump(ofp_data, f, indent=2)
            logging.info(f"\nFull OFP data saved to '{output_file}'")
            return True
        else:
            logging.error("Failed to fetch SimBrief OFP data")
            return False
    except Exception as e:
        logging.error(f"Error during SimBrief API test: {e}")
        return False


if __name__ == "__main__":
    success = test_simbrief_api()
    sys.exit(0 if success else 1)
