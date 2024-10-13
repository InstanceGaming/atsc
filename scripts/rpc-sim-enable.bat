@echo off
grpcurl -plaintext -proto protobufs/controller.proto -d "{\"enabled\":true}" localhost:7833 atsc.rpc.controller.Controller/set_presence_simulation
