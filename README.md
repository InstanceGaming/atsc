## Actuated Traffic Signal Controller

This is the result of 3 years of clean-room reverse engineering how real traffic signal controllers work for intersections.

This software aims to accurately simulate the functionality and customization of a modern, actuated traffic control system using industry standard concepts.

Do note, this software is NOT yet complete and is regularly changed and expanded with new features.

### Currently implemented

- Ring & barrier (limited customization)
- Actuation and timed modes
- Vehicle and pedestrian signals
- Flexible input signal handling and routing
- Call expiration timeout
- Multifaceted call sorting algorithm with weights
- Red clearance timing
- Configurable flash mode (red or yellow) per channel
- Time freeze mode
- Configuration schema validation
- CLI utility for validating configuration files standalone.
- Serial bus interface with custom HDLC frame protocol
- Live network monitor with Protobuf encapsulation
- Gap time & time to reduce (partial)
- Separation of vehicle and ped calls (groundwork laid)

### Up next for implementation

- Preemption for emergency vehicles
- Load switch flash mode
- Flashing yellow arrow
- (Needs re-work) Calendar and time-based scheduler

### Associated software

- (Not yet public) RTSV: Realtime traffic signal viewer. Qt5 GUI network utility for viewing live field indications remotely.
- (Not yet public) TFIB: Firmware for Arduino Mega. Transceiver device on HDLC bus for switching load switches, polling inputs and other real-time IO.

### Use

For demonstration setup, configure a virtual environment with Python 3.6 or higher. Then install the packages listed in `requirements.txt` (`pip install -r requirements.txt`).

Entrypoint for the control loop is `src/main.py`. Specify the following configuration files as ending arguments: `configs/device.json`, `configs/quick.json` OR `configs/long.json`, `configs/inputs.json`. 

Entrypoint for the CLI utility is `src/cli.py`. 

You can use the argument `-h` to view command line option help texts for all entrypoints.

_This readme last updated June 18th, 2022_
