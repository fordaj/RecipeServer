@echo off
setlocal
cd /d "%~dp0"
uv run python -m http.server 8000
endlocal
