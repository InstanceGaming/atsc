#!/bin/sh
PYTHONOPTIMIZE=2 screen -dmS atsc-fieldbus poetry run atsc-fb -L "debug,warning;stderr=error" -b 115200 /dev/ttyAMA0 $@
