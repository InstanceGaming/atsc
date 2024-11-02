#!/bin/sh
PYTHONOPTIMIZE=2
screen -dmS atsc poetry run atsc -a 0.0.0.0 --init-demand --presence-simulation $@
