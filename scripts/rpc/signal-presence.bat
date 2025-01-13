@echo off
poetry run grpcurl -plaintext -proto protobufs/controller.proto -d "{\"id\":%1,\"presence\":%2}" "%3:7833" atsc.rpc.controller.Controller/set_signal_presence
