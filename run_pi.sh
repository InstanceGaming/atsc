#!/usr/bin/env bash
ATSC_DIR=.
ENV_DIR=$ATSC_DIR/env/debian
INTERPRETER_DIR=$ENV_DIR/bin
INTERPRETER=python3
INTERPRETER_PATH=$INTERPRETER_DIR/$INTERPRETER
ATSC_PID_PATH=$ATSC_DIR/atsc.pid

if ! [ -x "$INTERPRETER_PATH" ];
then
  echo "Interpreter missing"

  if ! [ -d "$INTERPRETER_DIR" ];
  then
    echo "Creating virtual environment"

    $INTERPRETER -m venv $ENV_DIR

    if [ $? -ne 0 ];
    then
      exit 10000
    fi
  fi

  echo "Updating pip and installing pip-tools"
  $INTERPRETER_PATH -m pip install --upgrade pip
  $INTERPRETER_PATH -m pip install pip-tools

  if [ $? -ne 0 ];
  then
    exit 10001
  fi

  echo "Activating environment"
  source "$INTERPRETER_DIR/activate"
fi

pip-sync

if [ $? -ne 0 ];
then
  exit 10002
fi

$INTERPRETER_PATH -OO -m atsc.main --pid "$ATSC_PID_PATH" "$ATSC_DIR/configs/rpi.json" &
