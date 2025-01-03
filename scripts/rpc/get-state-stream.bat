@echo off
poetry run grpcurl -plaintext -proto protobufs/controller.proto -d "{\"poll_rate\":0.1,\"runtime_info\":false,\"field_outputs\":true,\"signals\":false}" localhost:7833 atsc.rpc.controller.Controller/get_state_stream
