@echo off
cd /d "C:\Users\Ryan.Casale\OneDrive - IQPC WBR\Field service East\fse_sdr_agent"
echo.
echo ========================================
echo   B2B Atlanta Prospecting Radar
echo ========================================
echo.
python radar.py --auto-add --event-id b2b-online-atlanta
echo.
echo Done! Check the pipeline tab in your app.
pause
