#!/bin/sh
PYTHONOPTIMIZE=2 screen -dmS atsc-fieldbus poetry run atsc-fb -L "debug,warning;stderr=error" --truncate-field-outputs 36 -b 115200 /dev/ttyAMA0 $@
