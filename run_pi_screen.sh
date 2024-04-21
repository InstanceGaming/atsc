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

screen -dmS atsc $INTERPRETER_PATH -OO -m atsc.main --pid "$ATSC_PID_PATH" "$ATSC_DIR/configs/185-rpi.json"
