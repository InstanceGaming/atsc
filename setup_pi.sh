#!/usr/bin/env bash
source ./env_pi.sh

if ! [ -x "$INTERPRETER_PATH" ];
then
  if ! [ -d "$INTERPRETER_DIR" ];
  then
    echo "Creating virtual environment"

    $INTERPRETER -m venv $ENV_DIR

    if [ $? -ne 0 ];
    then
      exit 10000
    fi
  fi

  echo "Installing packages"
  $INTERPRETER_PATH -m pip install --upgrade pip
  $INTERPRETER_PATH -m pip install -r requirements.txt

  if [ $? -ne 0 ];
  then
    exit 10001
  fi
fi
