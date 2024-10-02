@echo off
grpcurl -plaintext -proto protobufs/controller.proto localhost:7833 atsc.rpc.controller.Controller/get_metadata
