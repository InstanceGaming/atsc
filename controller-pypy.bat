@echo off
.\env\win32-pypy\scripts\pypy.exe -OO -m atsc.controller.main -a 0.0.0.0 --presence-simulation %*
