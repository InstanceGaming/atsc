## Actuated Traffic Signal Controller

This is the result of 4 years of clean-room reverse engineering how real traffic signal controllers work for intersections.

This software aims to simulate the functionality and customization of a modern, actuated traffic control systems as accurately as possible.

Do note, this software is nowhere near complete and is regularly torn up to accommodate new findings.

### Currently implemented
- Vehicle and pedestrian signals
- Red clearance timing
- Configurable flash mode (red or yellow) per channel
- Configuration schema validation
- Serial bus interface with custom HDLC frame protocol
- Gap time & time to reduce

### Up next for implementation

- Live controller state monitor TUI with Protobuf encapsulation built into the CLI utility.
- Preemption for emergency vehicles
- Load switch flash mode
- Flashing yellow arrow
- (Needs re-work) Calendar and time-based scheduler

### Use

For demonstration setup, configure a virtual environment with Python 3.10. Then install the packages listed in `requirements/production.txt` (`pip install -r requirements/production.txt`).

Entrypoint for the daemon process is `atsc/daemon/main.py`. To speed up tick rate, set `--tick-size`, default is 0.1.

Entrypoint for the CLI utility is `atsc/cli/main.py`. 

Entrypoints must be ran as modules, i.e. `python -m atsc.daemon.main` or `python -m atsc.cli.main`.

You can use the argument `-h` to view command line option help texts for all entrypoints.

_This readme last updated Feb 4th, 2023._
