@echo off
setlocal EnableExtensions
set "PYINSTALLER_RESET_ENVIRONMENT=1"
set "APP_EXE=%~1"
set "EXPECTED_VERSION=%~2"
set "START_MODE=%~3"

if not defined MAIL_AGENT_HEALTH_URL set "MAIL_AGENT_HEALTH_URL=http://127.0.0.1:8765/health"
set "MAIL_AGENT_EXPECTED_VERSION=%EXPECTED_VERSION%"
if defined LOCALAPPDATA (
  set "LOG_DIR=%LOCALAPPDATA%\Mail-Agent\logs"
) else (
  set "LOG_DIR=%TEMP%\Mail-Agent\logs"
)
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
set "LOG_FILE=%LOG_DIR%\update-restart.log"
set "MAIL_AGENT_UPDATE_LOG=%LOG_FILE%"

call :log "Restart helper started. Target=%APP_EXE% Version=%EXPECTED_VERSION% Mode=%START_MODE%"

if not exist "%APP_EXE%" goto fail_missing

rem Never trust a stale pre-update process. The installer has already replaced the files;
rem make sure the process serving the gateway is the newly installed executable.
taskkill /F /T /IM "Mail-Agent.exe" >nul 2>&1
timeout /t 1 /nobreak >nul

call :start_agent
call :wait_health
if not errorlevel 1 goto success

call :log "First restart did not expose the expected gateway. Retrying once."
taskkill /F /T /IM "Mail-Agent.exe" >nul 2>&1
timeout /t 2 /nobreak >nul
call :start_agent
call :wait_health
if not errorlevel 1 goto success

goto fail_health

:start_agent
call :log "Starting newly installed MAIL-AGENT."
if /I "%START_MODE%"=="open-browser" (
  start "" "%APP_EXE%"
) else (
  start "" "%APP_EXE%" --no-browser
)
if errorlevel 1 exit /b 1
exit /b 0

:wait_health
for /L %%I in (1,1,45) do (
  powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; try { $r=Invoke-RestMethod -Uri $env:MAIL_AGENT_HEALTH_URL -TimeoutSec 1; if (($r.service -eq 'mail-agent-gateway') -and ([string]::IsNullOrWhiteSpace($env:MAIL_AGENT_EXPECTED_VERSION) -or ($r.version -eq $env:MAIL_AGENT_EXPECTED_VERSION))) { exit 0 } } catch {}; exit 1" >nul 2>&1
  if not errorlevel 1 exit /b 0
  timeout /t 1 /nobreak >nul
)
exit /b 1

:success
call :log "Gateway is reachable with expected version %EXPECTED_VERSION%."
endlocal
exit /b 0

:fail_missing
set "MAIL_AGENT_UPDATE_ERROR=Die neu installierte Mail-Agent.exe wurde nicht gefunden."
call :log "ERROR: %MAIL_AGENT_UPDATE_ERROR%"
goto show_failure

:fail_health
set "MAIL_AGENT_UPDATE_ERROR=MAIL-AGENT wurde nach dem Update gestartet, aber das lokale Gateway der neuen Version wurde nicht erreichbar."
call :log "ERROR: %MAIL_AGENT_UPDATE_ERROR%"
goto show_failure

:show_failure
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "try { Add-Type -AssemblyName PresentationFramework; $nl=[Environment]::NewLine; $msg='MAIL-AGENT konnte nach dem Update nicht automatisch wiederhergestellt werden.'+$nl+$nl+$env:MAIL_AGENT_UPDATE_ERROR+$nl+$nl+'Diagnoseprotokoll: '+$env:MAIL_AGENT_UPDATE_LOG; [System.Windows.MessageBox]::Show($msg,'MAIL-AGENT - Updatefehler','OK','Error') | Out-Null } catch {}" >nul 2>&1
endlocal
exit /b 1

:log
>>"%LOG_FILE%" echo [%date% %time%] %~1
exit /b 0
