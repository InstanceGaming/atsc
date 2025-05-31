#!/usr/bin/env bash
source ./env_pi.sh

if ! [ -x "$INTERPRETER_PATH" ];
then
  echo "Interpreter missing"
  exit 10002
fi

$INTERPRETER_PATH -OO -m atsc.main -l "INFO,WARNING;stderr=ERROR;file=INFO,ERROR" "$ATSC_DIR/configs/rpi.json" &
