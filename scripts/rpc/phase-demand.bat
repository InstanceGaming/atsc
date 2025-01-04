@echo off
poetry run grpcurl -plaintext -proto protobufs/controller.proto -d "{\"id\":%1,\"demand\":true}" "%2:7833" atsc.rpc.controller.Controller/set_phase_demand
