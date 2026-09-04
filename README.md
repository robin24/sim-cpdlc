# Sim-CPDLC

A simple, screenreader-accessible CPDLC (Controller-Pilot Data Link Communications) client for [Hoppie's ACARS](https://www.hoppie.nl/acars/) and [SayIntentions.ai](https://sayintentions.ai) that allows pilots to communicate with air traffic control via text messages.

## Overview

Sim-CPDLC provides a user-friendly interface for Hoppie-compatible ACARS implementations, allowing for data link communications with ATC.

## Features

- **CPDLC Messaging**: Send and receive CPDLC messages with ATC
- **Pre-Departure Clearance (PDC)**: Request PDCs from departure airports
- **Altitude Change Requests**: Easily request altitude changes during flight
- **Weather Information**: Request METAR, TAF, short TAF and ATIS for any airport
- **Automatic Weather Updates**: Keep a report up to date and be notified only when it
  actually changes
- **TELEX Messaging**: Send free-text messages to any station
- **SimBrief Integration**: Automatically fetch flight details from your SimBrief flight plans
- **Message History**: View and respond to all received messages
- **Resilient link**: rides out network outages, announces a lost and a restored link, and keeps polling

## Installation

1. [Download the latest release](https://github.com/robin24/sim-cpdlc/releases/latest)
2. Run the downloaded .exe file and follow the installation prompts

### Install from Source
#### Prerequisites

- Python 3.12 or higher

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

### Main Window

The main window of Sim-CPDLC is very simple, and contains the following:

- Message list: holds all the messages you send and receive over the ACARS network, plus system status messages such as connection issues. Also provides the ability to acknowledge CPDLC messages using the context menu
- Read-only text field: shows the message selected in the list, making it easier to review message text using arrow keys.
- Menu bar: contains all the controls needed to use the client, connect to the network, etc.
- Status bar: shows your current network status. Can easily be read with NVDA by pressing NVDA+End while the Sim-CPDLC window is in focus

### Connecting to the Network

1. Click `File > Connect`
2. Select the network you want to connect to
3. Enter your aircraft callsign (e.g., `BAW123`)
4. The application will connect to the selected network

### Logging On to a Station

1. After connecting, go to `Requests > Logon`
2. Enter the four-letter code of the ATC station (e.g., `KUSA` for en route CPDLC within the US)
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
2. Enter the flight level as two or three digits without `FL` (`350` for FL350, `90` for FL090)
3. Optionally give a reason: weather or aircraft performance
4. Click OK to send the request

`Requests > Direct to`, `Requests > Speed change` and `Requests > When can we
expect` work the same way. Each dialog says what it accepts and only enables OK
for a value the network will take.

### Sending TELEX Messages

1. Go to `Requests > Telex message`
2. Enter:
   - Recipient: a station name or callsign of 3 to 8 letters or digits (your current station is filled in)
   - Message text: up to 220 plain-ASCII characters; the dialog counts them as you type
3. Click OK to send the message

### Requesting Weather

1. Go to `Requests > ATIS and Weather request`
2. Choose the report type: METAR, TAF, short TAF, or ATIS
3. Enter the airport ICAO code
4. Optionally check `Keep this report updated automatically`
5. Click OK

The report is added to the message list without the notification sound: you
asked for it, so there is nothing to announce. Automatic updates (below) do
play it, because they arrive unprompted.

### Automatic Weather Updates

Neither Hoppie nor SayIntentions push weather to the aircraft, so an automatic
update is a re-request on a timer. When a report is being kept up to date, the
client requests it again periodically and notifies you **only when it has
actually changed**: for an ATIS that means a new information letter, and for a
METAR or TAF a change to the report itself. A re-worded ATIS carrying the same
letter stays silent.

- Check `Keep this report updated automatically` in the weather request dialog to
  start watching a report

To stop watching one, use whichever is closest to hand:

- Select the report in the message list and press the Applications key (or
  right-click) for `Stop automatic updates`
- Request the same report again with the checkbox cleared. The checkbox always
  shows whether that airport and report type are currently being watched
  (unless you have already checked or unchecked it yourself in that dialog), so
  it turns updates off as readily as on
- `Requests > Automatic weather updates` lists everything being watched, and lets
  you check them all immediately, stop one, or stop all
- The interval is set in `File > Settings` and defaults to 5 minutes. Shorter
  intervals put more load on the ACARS network, so only lower it if you are
  watching an ATIS that changes often
- Watching stops automatically when you disconnect from the network

### Responding to Messages

1. After selecting a message that requires a response, either press the Application key or right-click to bring up the context menu
2. Select the appropriate response from the context menu (e.g., WILCO, UNABLE, ROGER)

### Disconnecting

1. Click `File > Disconnect` when you're finished
2. If you're logged on to a station, the application will automatically send a logoff message

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

## Running the Tests

Offline checks that need no network connection, simulator or logon code:

```bash
pip install -r requirements-dev.txt
pytest
```

See `tests/README.md` for what each file covers.

## Acknowledgements

- Huge thanks to islandcontroller for the wonderful [hoppie-connector](https://github.com/islandcontroller/hoppie-connector) Python package, without which this project would not have been possible
- Hoppie, developer and maintainer of the Hoppie's ACARS implementation and network infrastructure.
- [Dave Black](https://github.com/daveblackuk), developer of the  compatibility layer between Hoppie's ACARS and SayIntentions.

## License

This project is licensed under the MIT License - see the LICENSE file for details.