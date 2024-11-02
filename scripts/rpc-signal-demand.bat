@echo off
poetry run grpcurl -plaintext -proto protobufs/controller.proto -d "{\"id\":%1,\"demand\":true}" localhost:7833 atsc.rpc.controller.Controller/set_signal_demand
