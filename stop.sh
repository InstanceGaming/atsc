#!/usr/bin/env bash
source ./env_linux.sh
if screen -list | grep -q $ATSC_SCREEN; then
  screen -S $ATSC_SCREEN -p 0 -X quit
fi