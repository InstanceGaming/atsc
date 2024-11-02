@echo off
set LOOSEN_RPC_WATCHDOG=1
poetry run textual run --dev atsc.tui.main %*
