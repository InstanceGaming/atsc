## Actuated Traffic Signal Controller

_This readme last updated Nov 4th, 2024_

This is a toy traffic signal controller as part of a research project 
that has spanned 4-ish years of reverse engineering how North-American 
actuated traffic signal controllers work by attempting to re-implement 
all the functionality observed by real controllers. 

This software is NOT anywhere near complete or stable and is 
regularly changed and expanded with new features, not to imply this 
codebase should ever be used to control real traffic. It's a toy 
controller passion project after all. ;)

### Currently implemented

- Asynchronous codebase, `asyncio` (`uvloop` on Linux, `winloop` on Windows)
- Vehicle and pedestrian signals
- Ring & barrier
- Actuation with recycle
- Time freeze
- Green time extension
- Concurrent or sequential phasing
- Red clearance timing
- Flashing yellow arrow (pedestrian load switch spare output)
- Presence lockout
- gRPC-powered modularization
- Serial bus interface with custom HDLC frame protocol

### Associated software

- (Not yet published) TFIB: Firmware for Arduino Mega. Transceiver device on HDLC bus for switching load switches, polling inputs and other real-time IO.

### Use

- Install Python >=3.11.
- Install `poetry` (recommended way: `pipx install poetry`).
- Use poetry to set up and run.
  - While in repo root, run `poetry install --with dev,tui,fieldbus` to install all dependencies.

Entrypoints are:
- `atsc.controller.main` aka `atsc`
- `atsc.fieldbus.main` aka `atsc-fb`
- `atsc.networking.main` aka `atsc-net` (not implemented yet)
- `atsc.tui.main` aka `atsc-tui`

Project extras:

- `fieldbus` is a separate process which interconnects the `TFIB` device over serial link.
- `tui` is a text-based interface for viewing and interacting with the state of the controller.
- `dev` is for additional tooling like gRPC compiler, etc.

You can use the argument `-h` to view command line option help texts for all entrypoints.
