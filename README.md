# Sim-CPDLC

A simple, screenreader-accessible CPDLC (Controller-Pilot Data Link Communications) client for [Hoppie's ACARS](https://www.hoppie.nl/acars/) and [SayIntentions.ai](https://sayintentions.ai) that allows pilots to communicate with air traffic control via text messages.

## Overview

Sim-CPDLC provides a user-friendly interface for Hoppie-compatible ACARS implementations, allowing for data link communications with ATC.

## Features

- **CPDLC Messaging**: Send and receive CPDLC messages with ATC
- **Pre-Departure Clearance (PDC)**: Request PDCs from departure airports
- **Altitude Change Requests**: Easily request altitude changes during flight
- **TELEX Messaging**: Send free-text messages to any station
- **SimBrief Integration**: Automatically fetch flight details from your SimBrief flight plans
- **Message History**: View and respond to all received messages
- **Automatic Reconnection**: Handles connection issues gracefully

## Installation

1. [Download the latest release](https://github.com/robin24/sim-cpdlc/releases/latest)
2. Run the downloaded .exe file and follow the installation prompts

### Install from Source
#### Prerequisites

- Python 3.7 or higher

1. Clone this repository:
   ```bash
   git clone https://github.com/robin24/sim-cpdlc.git
   cd sim-cpdlc
   ```

2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the application:
   ```bash
   python3 app.py
   ```

## Usage Guide

### Connecting to the Network

1. Click `File > Connect`
2. Select the network you want to connect to
3. Enter your aircraft callsign (e.g., `BAW123`)
4. The application will connect to the selected network

### Logging On to a Station

1. After connecting, go to `Requests > Logon`
2. Enter the ICAO code of the ATC station (e.g., `KUSA` for en route CPDLC within the US)
3. Click OK to send the logon request

### Requesting Pre-Departure Clearance (PDC)

1. Go to `Requests > PDC`
2. Enter:
   - Origin airport ICAO code
   - Destination airport ICAO code
   - Aircraft type code
   - Stand number
   - ATIS information letter
   - Note: many of these fields will be filled automatically if you set your SimBrief ID in Settings
3. Click OK to send the PDC request

### Requesting Altitude Changes

1. Go to `Requests > Altitude change`
2. Select:
   - Desired altitude
   - Climb or descent
   - (Optional) Reason for the request
3. Click OK to send the request

### Sending TELEX Messages

1. Go to `Requests > Telex message`
2. Enter:
   - Recipient (ICAO code or callsign)
   - Message text
3. Click OK to send the message

### Responding to Messages

1. After selecting a message that requires a response, either press the Application key or right-click to bring up the context menu
2. Select the appropriate response from the context menu (e.g., WILCO, UNABLE, ROGER)

### Disconnecting

1. Click `File > Disconnect` when you're finished
2. If you're logged on to a station, the application will automatically send a logoff message



## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgements

- Huge thanks to islandcontroller for the wonderful [hoppie-connector](https://github.com/islandcontroller/hoppie-connector) Python package, without which this project would not have been possible
- Hoppie, developer and maintainer of the Hoppie's ACARS implementation and network infrastructure.
- [Dave Black](https://github.com/daveblackuk), developer of the  compatibility layer between Hoppie's ACARS and SayIntentions.
