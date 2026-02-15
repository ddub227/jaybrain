@echo off
REM Schedule the JayBrain Daily Briefing to run at 7:00 AM daily.
REM Run this script once (as Administrator) to create the scheduled task.
REM
REM The task runs under the current user account and requires the user
REM to be logged in (since OAuth tokens are stored in the user profile).

set PYTHON_PATH=python
set SCRIPT_DIR=%~dp0..
set WORKING_DIR=%SCRIPT_DIR%

REM Create the scheduled task
schtasks /create ^
    /tn "JayBrain Daily Briefing" ^
    /tr "\"%PYTHON_PATH%\" -m jaybrain.daily_briefing" ^
    /sc daily ^
    /st 07:00 ^
    /sd %date:~-4%/%date:~4,2%/%date:~7,2% ^
    /rl HIGHEST ^
    /f

if %ERRORLEVEL% EQU 0 (
    echo.
    echo Task "JayBrain Daily Briefing" created successfully.
    echo Schedule: Daily at 7:00 AM
    echo.
    echo To test it now, run:
    echo   schtasks /run /tn "JayBrain Daily Briefing"
    echo.
    echo To delete it later:
    echo   schtasks /delete /tn "JayBrain Daily Briefing" /f
) else (
    echo.
    echo Failed to create scheduled task.
    echo Try running this script as Administrator.
)

pause
