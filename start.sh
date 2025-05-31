#!/usr/bin/env bash
source ./env_linux.sh

if ! [ -x "$INTERPRETER_PATH" ];
then
  echo "Interpreter missing"
  source ./setup_pi.sh

  if [ $? -ne 0 ];
  then
    exit 10002
  fi
fi

screen -dmS $ATSC_SCREEN "$INTERPRETER_PATH" -OO -m atsc.main -l "FIELDS,WARNING;stderr=ERROR;file=INFO,ERROR" "$ATSC_DIR/configs/rpi.json"