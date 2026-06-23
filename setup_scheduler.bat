@echo off
echo Setting up FSE Radar daily schedule...

schtasks /create /tn "FSE Radar" /tr "\"C:\Users\Ryan.Casale\OneDrive - IQPC WBR\Field service East\fse_sdr_agent\run_radar.bat\"" /sc daily /st 08:00 /f

if %ERRORLEVEL% EQU 0 (
    echo.
    echo Done! FSE Radar will run every morning at 8:00 AM.
    echo New companies will be auto-added to your pipeline and synced to GitHub.
) else (
    echo.
    echo Something went wrong. Try running this as Administrator.
)
pause
