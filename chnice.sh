#!/usr/bin/env bash
ATSC_PID_FILE=/home/pi/atsc/atsc.pid

if [ -r $ATSC_PID_FILE ]; then
        renice -20 "$(cat $ATSC_PID_FILE)"
fi
