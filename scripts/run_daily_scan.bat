@echo off
REM ---------------------------------------------------------------------------
REM Oweru Tech Solutions - daily website health auto-scan
REM Run by Windows Task Scheduler once a day.
REM Writes a timestamped log so you can always see what happened.
REM ---------------------------------------------------------------------------
setlocal

set "PROJECT_DIR=C:\Users\Latitude E5450\Desktop\OWERU TECH_SOLUTION"
set "PYTHON=%PROJECT_DIR%\venv\Scripts\python.exe"
set "LOG_DIR=%PROJECT_DIR%\logs"
set "LOG_FILE=%LOG_DIR%\daily_scan.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo. >> "%LOG_FILE%"
echo ==== RUN %date% %time% ==== >> "%LOG_FILE%"

cd /d "%PROJECT_DIR%"

if not exist "%PYTHON%" (
    echo ERROR: python not found at %PYTHON% >> "%LOG_FILE%"
    exit /b 1
)

"%PYTHON%" manage.py daily_scan >> "%LOG_FILE%" 2>&1
set "EXITCODE=%ERRORLEVEL%"

if %EXITCODE% neq 0 (
    echo ERROR: daily_scan exited with code %EXITCODE% >> "%LOG_FILE%"
) else (
    echo OK: daily_scan finished successfully >> "%LOG_FILE%"
)

echo ==== END %date% %time% (exit %EXITCODE%) ==== >> "%LOG_FILE%"
exit /b %EXITCODE%
