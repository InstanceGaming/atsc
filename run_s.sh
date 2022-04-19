#!/usr/bin/env bash
screen -S atsc env/bin/python3 -O src/main.py --pid atsc.pid configs/rpi4.json configs/inputs.json configs/long.json
