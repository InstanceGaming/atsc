#!/usr/bin/env bash
screen -S atsc ./env/bin/python3 -OO -m atsc.cli control --pid atsc.pid
