#!/bin/sh
PYTHONOPTIMIZE=2 screen -dmS atsc-controller poetry run atsc -L "debug,warning;stderr=error" -a 0.0.0.0 --init-demand --presence-simulation $@
