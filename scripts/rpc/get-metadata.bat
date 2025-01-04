@echo off
poetry run grpcurl -plaintext -proto protobufs/controller.proto "%2:7833" atsc.rpc.controller.Controller/get_metadata
