@echo off
set LOOSEN_RPC_WATCHDOG=1
.\env\win32\scripts\textual.exe run --dev atsc.tui.main %*
