@echo off

protoc -I=src\proto --python_out=src\proto src\proto\*.proto