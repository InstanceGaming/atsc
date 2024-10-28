@echo off
.\env\win32\scripts\python.exe -OO -m atsc.controller.main -a 0.0.0.0 --init-demand --presence-simulation %*
