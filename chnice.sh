#!/usr/bin/env bash
ATSC_PID_FILE=atsc.pid

if [ -r $ATSC_PID_FILE ]; then
        renice 19 "$(cat $ATSC_PID_FILE)"
fi
