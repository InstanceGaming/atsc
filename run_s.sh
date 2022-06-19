#!/usr/bin/env bash
screen -S atsc env/bin/python3 -OO src/main.py --pid atsc.pid configs/rpi_long1.json
