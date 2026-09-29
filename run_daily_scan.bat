@echo off
REM Runs the Oweru daily auto-scan (up to 50 websites).
REM Used by Windows Task Scheduler. Logs output to daily_scan.log.
cd /d "%~dp0"
set PYTHON=venv\Scripts\python.exe
set PROJECT=manage.py
echo [%date% %time%] Starting daily scan >> daily_scan.log
%PYTHON% %PROJECT% daily_scan >> daily_scan.log 2>&1
echo [%date% %time%] Daily scan finished >> daily_scan.log