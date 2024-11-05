@echo off
poetry run python -OO -m grpc_tools.protoc -I . --python_betterproto_out . protobufs/*.proto
