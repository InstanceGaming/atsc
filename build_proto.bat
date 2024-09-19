@echo off
protoc -I=atsc\proto --python_out=atsc\proto atsc\proto\*.proto
