@echo off
poetry run atsc -a 0.0.0.0 --init-demand --presence-simulation %*
