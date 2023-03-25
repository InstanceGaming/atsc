@echo off
env\Scripts\python -m grpc_tools.protoc -I atsc\rpc\ --python_out=atsc\rpc\ --pyi_out=atsc\rpc\ --grpc_python_out=atsc\rpc\ atsc\rpc\*.proto
rem https://stackoverflow.com/questions/60427471/generate-correct-import-using-protoc-in-python
env\Scripts\2to3 atsc\rpc -w -n
