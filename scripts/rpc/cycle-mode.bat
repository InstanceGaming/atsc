@echo off
poetry run grpcurl -plaintext -proto protobufs/controller.proto -d "{\"cycle_mode\":%1}" "%2:7833" atsc.rpc.controller.Controller/set_cycle_mode
