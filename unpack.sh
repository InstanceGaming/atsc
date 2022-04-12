#!/usr/bin/env bash
cd ~/atsc || exit
unzip -o atsc.zip
dos2unix **/*
rm *.bat
sudo chmod +x **/*.sh
rm atsc.zip
