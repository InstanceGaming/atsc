@echo off
.\env\win32\scripts\python -OO -m atsc.main -l "FIELDS,WARNING;stderr=ERROR;file=FIELDS,ERROR" configs/dev1.json