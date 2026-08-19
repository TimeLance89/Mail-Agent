@echo off
setlocal
set "PYINSTALLER_RESET_ENVIRONMENT=1"
start "" "%~1"
endlocal
exit /b 0
