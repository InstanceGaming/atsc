@echo off
grpcurl -plaintext -proto protobufs/controller.proto -d "{\"time_freeze\":true}" localhost:7833 atsc.rpc.controller.Controller/set_time_freeze
