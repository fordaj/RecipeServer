@echo off
setlocal
cd /d "%~dp0"
uv run python -m recipeserver
endlocal
