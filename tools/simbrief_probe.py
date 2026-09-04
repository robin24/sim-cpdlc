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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
