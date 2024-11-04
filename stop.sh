#!/bin/sh
if screen -list | grep -q "atsc"; then
  screen -X atsc -X stuff "^C"
fi
