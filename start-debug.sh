#!/bin/sh
screen -dmS atsc poetry run atsc -L "verbose,warning;stderr=error" -a 0.0.0.0 --init-demand --presence-simulation $@
