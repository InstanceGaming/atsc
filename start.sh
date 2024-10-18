#!/bin/sh
screen -dmS atsc ./env/bin/python3 -OO -m atsc.controller.main -a 0.0.0.0 --init-demand --simulate-presence
