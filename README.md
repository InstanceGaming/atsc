## Actuated Traffic Signal SimpleController

This is the result of 4 years of clean-room reverse engineering how real traffic signal controllers work for intersections.

This software aims to accurately simulate the functionality and customization of a modern, actuated traffic control system using industry standard concepts.

Do note, this software is NOT anywhere near complete or stable and is regularly changed and expanded with new features. It's a passion project after all. ;)

### Currently implemented

- Async IO design
- Ring & barrier
- Actuation with recycle
- Vehicle and pedestrian signals
- Red clearance timing
- Serial bus interface with custom HDLC frame protocol

### Associated software

- (Not yet published) RTSV: Realtime traffic signal viewer. Qt5 GUI network utility for viewing live field indications remotely.
- (Not yet published) TFIB: Firmware for Arduino Mega. Transceiver device on HDLC bus for switching load switches, polling inputs and other real-time IO.

### Use

For demonstration setup, configure a virtual environment with Python >=3.11. Then install, like `pip install .`, with desired extras, `fieldbus`, `tui` or `dev`.

Entrypoints are:
- `atsc.controller.main`
- `atsc.fieldbus.main`
- `atsc.networking.main`

Extras:

- `fieldbus` is a separate process which interconnects the `TFIB` device over serial link.
- `tui` is a text-based interface for viewing and interacting with the state of the controller.
- `dev` is for additional tooling like gRPC compiler, etc.

You can use the argument `-h` to view command line option help texts for all entrypoints.

_This readme last updated Sep 22nd, 2024_
