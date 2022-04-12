@echo off

IF EXIST "env\scripts\python.exe" (
  .\env\scripts\python.exe src\main.py %* --no-pid configs\device.json configs\quick.json -vv
) ELSE (
  echo Could not find python.exe
)
PAUSE