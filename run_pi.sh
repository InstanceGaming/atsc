#!/usr/bin/env bash
source ./env_pi.sh

if ! [ -x "$INTERPRETER_PATH" ];
then
  echo "Interpreter missing"
  exit 10002
fi

$INTERPRETER_PATH -OO -m atsc.main --pid "$ATSC_PID_PATH" "$ATSC_DIR/configs/rpi.json" &
