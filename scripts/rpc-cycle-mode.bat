@echo off
grpcurl -plaintext -proto protobufs/controller.proto -d "{\"cycle_mode\":%1}" localhost:7833 atsc.rpc.controller.Controller/set_cycle_mode
