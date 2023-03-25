#!/usr/bin/env bash
screen -S atsc env/bin/python3 -OO -m atsc/daemon/main.py --pid atsc.pid configs/rpi_long1.json
