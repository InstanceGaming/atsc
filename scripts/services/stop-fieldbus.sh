#!/bin/sh
if screen -list | grep -q "atsc-fieldbus"; then
  screen -X atsc-fieldbus -X stuff "^C"
fi
