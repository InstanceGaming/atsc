#!/usr/bin/env bash
source ./env_pi.sh

if ! [ -x "$INTERPRETER_PATH" ];
then
  echo "Interpreter missing"
  source ./setup_pi.sh

  if [ $? -ne 0 ];
  then
    exit 10002
  fi
fi

$INTERPRETER_PATH -m atsc.main --pid "$ATSC_PID_PATH" "$ATSC_DIR/configs/rpi.json"
