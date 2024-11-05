#!/bin/sh
if screen -list | grep -q "atsc-controller"; then
  screen -X atsc-controller -X stuff "^C"
fi
