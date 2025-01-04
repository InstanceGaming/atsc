@echo off
poetry run grpcurl -plaintext -proto protobufs/controller.proto -d "{\"enabled\":true}" "%2:7833" atsc.rpc.controller.Controller/set_fya_enabled
