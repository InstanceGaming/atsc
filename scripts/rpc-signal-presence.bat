@echo off
grpcurl -plaintext -proto protobufs/controller.proto -d "{\"id\":%1,\"presence\":%2}" localhost:7833 atsc.rpc.controller.Controller/set_signal_presence
