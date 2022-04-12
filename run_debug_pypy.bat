@echo off

IF EXIST "env\scripts\pypy3.exe" (
  .\env\scripts\pypy3.exe src\main.py %* --no-pid configs\device.json configs\quick.json -vv
) ELSE (
  echo Could not find pypy3.exe
)
PAUSE